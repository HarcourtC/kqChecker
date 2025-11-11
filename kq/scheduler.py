"""Scheduler module: load weekly schedule and run an always-on scheduler."""
import json
import logging
import threading
import time
from datetime import datetime, timedelta, date
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Any, Dict

from .inquiry import post_attendance_query


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


def setup_logging(log_file: Path = Path(__file__).parent.parent / "attendance.log") -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def check_attendance(event_time, entries, dry_run: bool = False) -> None:
    # entries: list of dicts {course, room, raw}
    course_names = [e.get('course') if isinstance(e, dict) else str(e) for e in entries]
    logging.info("checking attendance for %s at %s", course_names, event_time.isoformat())
    try:
        if dry_run:
            logging.info("dry-run enabled: skipping network call for %s", course_names)
            return

        found = post_attendance_query(event_time, courses=entries)
        if found:
            logging.info("attendance records found for %s", course_names)
        else:
            logging.info("no attendance records for %s", course_names)
    except Exception:
        logging.exception("error querying attendance for %s", course_names)


def scheduler_loop(poll_interval: int = 30) -> None:
    processed = set()
    logging.info("scheduler started, watching %s", SCHEDULE_FILE)
    last_weekly_refresh = None  # type: ignore
    while True:
        try:
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
