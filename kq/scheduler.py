"""Scheduler module: load weekly schedule and run an always-on scheduler."""
import json
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from datetime import datetime, timedelta, date, time as dt_time
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Any, Dict, Optional

from .inquiry import post_attendance_query, API400Error
from .config import load_config
from .notifier import send_miss_email_async
from .error_handler import handle_api400
import socket


ROOT = Path(__file__).parent.parent
SCHEDULE_FILE = ROOT / "weekly.json"


def load_schedule(path: Path = SCHEDULE_FILE) -> List[Tuple[datetime, List[Dict[str, Any]]]]:
    if not path.exists():
        logging.warning("schedule file not found: %s", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("failed to read schedule file")
        return []

    events = []
    for k, v in raw.items():
        try:
            dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
        except Exception:
            logging.warning("unrecognized datetime format, skipping: %s", k)
            continue
        if not isinstance(v, list):
            logging.warning("unexpected value for %s, expected list", k)
            continue
        # normalize each item to an entry dict: {course, room, raw}
        entries: List[Dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict) and 'course' in item:
                entries.append(item)
            elif isinstance(item, str):
                entries.append({'course': item, 'room': None, 'raw': None})
            else:
                # unknown shape: attempt best-effort extraction
                try:
                    course = str(item)
                except Exception:
                    course = ''
                entries.append({'course': course, 'room': None, 'raw': item})
        events.append((dt, entries))

    events.sort(key=lambda x: x[0])
    return events


def setup_logging(log_file: Optional[Path] = None) -> None:
    # Ensure logs directory exists
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / "attendance.log"
    try:
        rotating_handler = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=20, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        rotating_handler.setFormatter(formatter)
        rotating_handler.setLevel(logging.INFO)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                rotating_handler,
                logging.StreamHandler(),
            ],
        )
    except Exception:
        # Fallback to console-only if file handler cannot be created
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Update root-level attendance.log marker for compatibility
    try:
        root_link = ROOT / "attendance.log"
        root_link.write_text(f"Current log file: logs/{log_path.name}\n", encoding="utf-8")
    except Exception:
        logging.debug("could not write root attendance.log marker")


POST_WINDOW_START = dt_time(7, 40)
POST_WINDOW_END = dt_time(19, 40)


def check_attendance(event_time, entries, dry_run: bool = False) -> None:
    # entries: list of dicts {course, room, raw}
    course_names = [e.get('course') if isinstance(e, dict) else str(e) for e in entries]
    logging.info("checking attendance for %s at %s", course_names, event_time.isoformat())
    try:
        if dry_run:
            logging.info("dry-run enabled: skipping network call for %s", course_names)
            return
        # Only send notification at the 5-minute mark before class.
        now = datetime.now()
        minutes_before = (event_time - now).total_seconds() / 60.0
        if not (0 < minutes_before <= 5):
            logging.info("not the notify moment (%.1f minutes before); skipping for %s", minutes_before, course_names)
            return

        # Enforce posting window: only perform network POSTs between POST_WINDOW_START and POST_WINDOW_END
        now_time = now.time()
        if not (POST_WINDOW_START <= now_time <= POST_WINDOW_END):
            logging.info(
                "outside posting window (%s - %s): skipping network call for %s",
                POST_WINDOW_START.isoformat(),
                POST_WINDOW_END.isoformat(),
                course_names,
            )
            return

        try:
            found = post_attendance_query(event_time, courses=entries)
            if found:
                logging.info("attendance records found for %s", course_names)
            else:
                logging.info("no attendance records for %s", course_names)
        except API400Error as e:
            cfg = load_config() or {}
            # delegate handling to centralized error handler which will send mail, save dumps, and exit
            handle_api400(cfg, e)
    except Exception:
        logging.exception("error querying attendance for %s", course_names)


def scheduler_loop(poll_interval: int = 300) -> None:
    processed = set()
    logging.info("scheduler started, watching %s", SCHEDULE_FILE)
    last_weekly_refresh = None  # type: ignore
    while True:
        try:
            # heartbeat tick to indicate scheduler is alive (helps when no events are due)
            logging.info("scheduler tick: now=%s", datetime.now().isoformat())

            now = datetime.now()
            events = load_schedule()
            for start_dt, courses in events:
                # courses is a list of entry dicts; build a stable key from course names
                names = [str(c.get('course') if isinstance(c, dict) else c or '') for c in courses]
                key = f"{start_dt.isoformat()}|{','.join(names)}"
                if key in processed:
                    continue
                check_time = start_dt - timedelta(minutes=5)
                if now >= start_dt:
                    processed.add(key)
                    continue
                if check_time <= now < start_dt:
                    logging.info("triggering attendance check for %s (starts at %s)", courses, start_dt)
                    try:
                        check_attendance(start_dt, courses)
                    except Exception:
                        logging.exception("error while checking attendance for %s", start_dt)
                    processed.add(key)
            time.sleep(poll_interval)
            # Weekly Sunday refresh: run once per Sunday
            try:
                today = date.today()
                # Python weekday(): Monday=0 ... Sunday=6
                if today.weekday() == 6 and last_weekly_refresh != today:
                    logging.info("weekly refresh: detected Sunday, regenerating weekly.json and saving raw response")
                    try:
                        # run get_weekly_json.py to regenerate weekly.json (uses same interpreter)
                        gw = Path(__file__).parent.parent / 'get_weekly_json.py'
                        if gw.exists():
                            subprocess.run([sys.executable, str(gw)], check=True)
                        else:
                            logging.warning("get_weekly_json.py not found at %s, skipping regeneration", gw)

                        # note: saving raw responses removed (script deleted); keep only regeneration
                    except subprocess.CalledProcessError:
                        logging.exception("weekly refresh subprocess failed")
                    except Exception:
                        logging.exception("unexpected error during weekly refresh")
                    last_weekly_refresh = today
            except Exception:
                logging.exception("error checking weekly refresh condition")
        except KeyboardInterrupt:
            logging.info("scheduler received KeyboardInterrupt, exiting")
            break
        except Exception:
            logging.exception("unexpected error in scheduler loop")
            time.sleep(poll_interval)


def main() -> None:
    setup_logging()
    logging.info("attendance scheduler starting up")
    # load config and optionally send a startup notification
    try:
        cfg = load_config() or {}
        notifs = cfg.get("notifications") or {}
        if notifs.get("on_startup"):
            now = datetime.now()
            hostname = ""
            try:
                hostname = socket.gethostname()
            except Exception:
                hostname = "unknown"

            # prepare context for formatting
            context = {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "host": hostname,
            }

            # allow optional templates in config: startup_subject/startup_body
            tpl_subj = notifs.get("startup_subject")
            tpl_body = notifs.get("startup_body")
            # safe formatting fallback
            class _SafeDict(dict):
                def __missing__(self, key):
                    return ""

            sd = _SafeDict()
            sd.update(context)

            subj = None
            body = None
            try:
                if tpl_subj:
                    subj = tpl_subj.format_map(sd)
            except Exception:
                subj = None
            try:
                if tpl_body:
                    body = tpl_body.format_map(sd)
            except Exception:
                body = None

            if not subj:
                subj = f"kqChecker started on {hostname} at {context['time']}"
            if not body:
                body = f"kqChecker scheduler started on {hostname} at {context['date']} {context['time']}.\nThis is an automated startup notification."

            try:
                # send asynchronously so startup isn't blocked
                send_miss_email_async(cfg, subject=subj, body=body, context=context)
                logging.info("startup notification scheduled (on_startup enabled)")
            except Exception:
                logging.exception("failed to schedule startup notification")
    except Exception:
        logging.debug("error while attempting to send startup notification", exc_info=True)
    t = threading.Thread(target=scheduler_loop, name="scheduler", daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(timeout=1)
    except KeyboardInterrupt:
        logging.info("received Ctrl+C, shutting down")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="kq.scheduler: run attendance scheduler or one-shot/test runs")
    parser.add_argument("--once", action="store_true", help="Run one immediate pass: process events due within the next 5 minutes and exit")
    parser.add_argument("--test", action="store_true", help="Test run: invoke check_attendance for the next scheduled event and exit")
    parser.add_argument("--dry-run", action="store_true", help="When used with --once or --test, skip network calls and only exercise the flow")
    parser.add_argument("--schedule", "-s", help="Path to schedule JSON file (defaults to project's weekly.json)")
    args = parser.parse_args()

    setup_logging()
    now = datetime.now()
    if args.once:
        events = load_schedule(Path(args.schedule) if args.schedule else SCHEDULE_FILE)
        for start_dt, courses in events:
            check_time = start_dt - timedelta(minutes=5)
            if check_time <= now < start_dt:
                logging.info("one-shot: triggering attendance check for %s (starts at %s)", courses, start_dt)
                check_attendance(start_dt, courses, dry_run=args.dry_run)
        logging.info("one-shot run complete")
    elif args.test:
        events = load_schedule(Path(args.schedule) if args.schedule else SCHEDULE_FILE)
        next_ev = None
        for start_dt, courses in events:
            if start_dt > now:
                next_ev = (start_dt, courses)
                break
        if next_ev:
            start_dt, courses = next_ev
            logging.info("test run: invoking check_attendance for next event %s (starts at %s)", courses, start_dt)
            check_attendance(start_dt, courses, dry_run=args.dry_run)
        else:
            logging.info("no future events found for test run")
    else:
        main()
