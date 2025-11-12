"""Inquiry module: handles attendance POST and response cleaning."""
from pathlib import Path
import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

try:
    import requests
except Exception:
    requests = None

from .config import load_config
from .matcher import match_records_by_time
from .notifier import send_miss_email_async


def post_attendance_query(event_time, courses=None, pageSize: int = 10, current: int = 1, calendarBh: str = "", timeout: int = 10, retries: int = 2, extra_headers: Optional[Dict[str, str]] = None) -> bool:
    """Construct payload and POST to api2; returns True if matching records found, else False."""
    from datetime import datetime

    if not isinstance(event_time, datetime):
        logging.warning("post_attendance_query: event_time should be datetime, got %s", type(event_time))

    date_str = event_time.strftime("%Y-%m-%d")
    payload = {
        "calendarBh": calendarBh,
        "startdate": date_str,
        "enddate": date_str,
        "pageSize": pageSize,
        "current": current,
    }

    cfg = load_config()
    base_headers = cfg.get("headers", {}) or {}
    headers = base_headers.copy()
    if extra_headers:
        headers.update(extra_headers)

    try:
        if requests is None:
            logging.error("requests library not available. Install via 'pip install requests'")
            return False

        url = cfg.get("api2")
        if not url:
            logging.error("api2 URL not configured in config.json")
            return False

        session = requests.Session()
        last_exc = None
        for attempt in range(retries + 1):
            try:
                logging.debug("POST %s attempt %d payload=%s headers=%s", url, attempt + 1, payload, headers)
                resp = session.post(url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
                try:
                    resp_json = resp.json()
                except ValueError:
                    logging.warning("api2 returned non-json response; returning False")
                    return False

                if courses:
                    # normalize courses which may be list of strings or list of structured entries
                    course_names: List[str] = []
                    scheduled_entries: List[Dict[str, Any]] = []
                    if isinstance(courses, list):
                        for c in courses:
                            if isinstance(c, dict):
                                cn = c.get('course')
                                if cn:
                                    course_names.append(str(cn))
                                # capture scheduled entry for notification context
                                scheduled_entries.append({
                                    'course': c.get('course'),
                                    'room': c.get('room'),
                                    'raw': c.get('raw'),
                                })
                            elif isinstance(c, str):
                                course_names.append(c)
                                scheduled_entries.append({'course': c, 'room': None, 'raw': None})
                    elif isinstance(courses, str):
                        course_names = [courses]
                        scheduled_entries = [{'course': courses, 'room': None, 'raw': None}]
                    else:
                        # fallback
                        try:
                            course_names = [str(courses)]
                        except Exception:
                            course_names = []

                    matched = extract_course_records(resp_json, course_names)
                    if not matched:
                            logging.info("no direct name-based attendance records found for courses=%s on %s", courses, date_str)
                            # time-based fallback: build a minimal weekly mapping for this event time
                            try:
                                # time-based matching expects weekly mapping to course name list
                                weekly_single = {event_time.strftime("%Y-%m-%d %H:%M:%S"): course_names}
                                # use -20/+5 minute window as tested previously
                                time_matches = match_records_by_time(resp_json, weekly_single, date_prefix=date_str,
                                                                     before_minutes=20, after_minutes=5,
                                                                     time_fields=("operdate", "watertime", "intime"))
                                total_candidates = sum(len(v) for v in time_matches.values())
                                if total_candidates:
                                    logging.info("time-based matching found %d candidate attendance record(s) for courses=%s on %s", total_candidates, course_names, date_str)
                                    # attempt to verify by room/location: only accept time-match if record's room matches scheduled room
                                    def _extract_room_from_record(r):
                                        try:
                                            # possible shapes: top-level roomBean.roomnum or nested classWaterBean.roomBean.roomnum
                                            room = None
                                            if isinstance(r.get("roomBean"), dict):
                                                room = r.get("roomBean", {}).get("roomnum")
                                            if not room:
                                                cw = r.get("classWaterBean") or {}
                                                rb = cw.get("roomBean") or {}
                                                if isinstance(rb, dict):
                                                    room = rb.get("roomnum")
                                            # sometimes room may be a simple string field
                                            if not room:
                                                room = r.get("room") or r.get("roomnum")
                                            # device identifiers that map to room (eqno/eqname/rbh)
                                            if not room:
                                                # eqno often looks like '教2楼-西403' per API
                                                eqno = r.get("eqno") or r.get("eqName") or r.get("eqname")
                                                if isinstance(eqno, str) and eqno:
                                                    return eqno.strip()
                                                # rbh/bh may be numeric device ids
                                                rbh = r.get("rbh") or r.get("bh")
                                                if rbh:
                                                    return str(rbh)
                                            if isinstance(room, str):
                                                return room.strip()
                                        except Exception:
                                            pass
                                        return None

                                    import re

                                    def _norm(s):
                                        if not s:
                                            return ""
                                        # keep CJK unified ideographs and ASCII letters/digits
                                        parts = re.findall(r"[\u4e00-\u9fff0-9A-Za-z]+", str(s))
                                        return "".join(parts).lower()

                                    matched_by_room = False
                                    # weekly_single maps the datetime key to course_names order
                                    for k, recs in time_matches.items():
                                        # find index(es) of the course_name(s) for this key
                                        scheduled_course_names = weekly_single.get(k, [])
                                        for idx, course_name in enumerate(scheduled_course_names):
                                            scheduled_room = None
                                            try:
                                                scheduled_room = scheduled_entries[idx].get('room') if idx < len(scheduled_entries) else None
                                            except Exception:
                                                scheduled_room = None
                                            for r in recs:
                                                rec_room = None
                                                try:
                                                    rec_room = _extract_room_from_record(r)
                                                    snippet = {
                                                        "operdate": r.get("operdate") or r.get("watertime") or r.get("intime"),
                                                        "teacher": r.get("teachNameList"),
                                                        "subject": (r.get("subjectBean") or {}).get("sName") if isinstance(r.get("subjectBean"), dict) else None,
                                                        "rec_room": rec_room,
                                                        "sched_room": scheduled_room,
                                                    }
                                                    logging.debug("time-match candidate for %s: %s", k, snippet)
                                                except Exception:
                                                    logging.debug("error while logging time-match candidate", exc_info=True)
                                                # compare normalized room strings (if both present)
                                                if scheduled_room and rec_room:
                                                    if _norm(scheduled_room) in _norm(rec_room) or _norm(rec_room) in _norm(scheduled_room):
                                                        logging.info("time+room match accepted for course=%s on %s (rec_room=%s sched_room=%s)", course_name, date_str, rec_room, scheduled_room)
                                                        matched_by_room = True
                                                        break
                                            if matched_by_room:
                                                break
                                        if matched_by_room:
                                            break
                                    if matched_by_room:
                                        # accept as matched (time + room)
                                        return True
                                    else:
                                        logging.info("time-based candidates found but none matched by room for courses=%s on %s", course_names, date_str)
                                        # prepare structured candidate summary for logs to aid debugging
                                        try:
                                            cand_list = []
                                            for k2, recs2 in time_matches.items():
                                                for r2 in recs2:
                                                    cand = {
                                                        "when": r2.get("operdate") or r2.get("watertime") or r2.get("intime"),
                                                        "eqno": r2.get("eqno"),
                                                        "rbh": r2.get("rbh") or r2.get("bh"),
                                                        "cardId": r2.get("cardId") or r2.get("cardid"),
                                                        "watertime": r2.get("watertime"),
                                                        "intime": r2.get("intime"),
                                                        "subject": (r2.get("subjectBean") or {}).get("sName") if isinstance(r2.get("subjectBean"), dict) else None,
                                                        "rec_room": _extract_room_from_record(r2),
                                                        "keys": list(r2.keys())[:20],
                                                    }
                                                    cand_list.append(cand)
                                            # log as JSON (ensure_ascii False for readable CJK in logs)
                                            logging.info("time-match candidates detail: %s", json.dumps(cand_list, ensure_ascii=False))
                                        except Exception:
                                            logging.debug("failed to serialize time-match candidates for logging", exc_info=True)
                                else:
                                    logging.info("no time-based candidates found either for courses=%s on %s", course_names, date_str)
                            except Exception:
                                logging.exception("time-based fallback matching failed")

                            # if we reach here, neither name-based nor time-based matching found records -> save debug info and send notification
                            try:
                                cfg = load_config() or {}

                                # save the POST response and payload for debugging if enabled in config
                                try:
                                    dbg = cfg.get("debug") or {}
                                    if dbg.get("save_missing_response") and resp_json is not None:
                                        dump_dir = Path(__file__).parent.parent / (dbg.get("dump_dir") or "debug_responses")
                                        dump_dir.mkdir(parents=True, exist_ok=True)
                                        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
                                        # sanitize course names for filename
                                        safe_courses = "-".join([str(c).replace(' ', '_') for c in course_names]) if course_names else "courses"
                                        fname = f"missing_{date_str}_{safe_courses}_{ts}.json"
                                        import re
                                        fname = re.sub(r"[^0-9A-Za-z_\-\.\u4e00-\u9fff]", "", fname)
                                        outp = dump_dir / fname
                                        try:
                                            with outp.open("w", encoding="utf-8") as fh:
                                                json.dump({"payload": payload, "response": resp_json}, fh, ensure_ascii=False, indent=2)
                                            logging.info("saved missing POST response to %s", outp)
                                        except Exception:
                                            logging.exception("failed to write missing POST response to %s", outp)
                                except Exception:
                                    logging.debug("error while attempting to save missing response for debugging", exc_info=True)

                                # build a small candidates summary (empty here)
                                context = {
                                    "courses": course_names,
                                    "date": date_str,
                                    # include scheduled entries (course + room) to display in the notification
                                    "candidates": scheduled_entries,
                                }

                                # send asynchronously so scheduler isn't blocked; subject/body will be rendered from config templates
                                send_miss_email_async(cfg, subject=None, body=None, context=context)
                            except Exception:
                                logging.exception("failed to send miss-notification email")
                            return False
                    cleaned = clean_records(matched)
                    logging.info("found %d matching attendance record(s)", len(cleaned))
                    # Optionally send a notification when matches are detected (config-controlled)
                    try:
                        cfg = load_config() or {}
                        notifs = cfg.get("notifications") or {}
                        if notifs.get("on_match"):
                            # prepare context for notification
                            context = {
                                "courses": course_names,
                                "date": date_str,
                                "matches": cleaned,
                            }

                            # allow optional templates in config: match_subject/match_body
                            tpl_subj = notifs.get("match_subject")
                            tpl_body = notifs.get("match_body")

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
                                subj = f"Attendance records found for {', '.join(course_names)} on {date_str}"
                            if not body:
                                # basic body summarizing matches
                                try:
                                    mlines = []
                                    for m in cleaned:
                                        mlines.append(f"- {m.get('operdate')} | {m.get('course')} | {m.get('room')} | {m.get('teacher')}")
                                    body = "Attendance records detected:\n" + "\n".join(mlines)
                                except Exception:
                                    body = "Attendance records were detected."

                            try:
                                send_miss_email_async(cfg, subject=subj, body=body, context=context)
                                logging.info("match notification scheduled (on_match enabled)")
                            except Exception:
                                logging.exception("failed to schedule match notification")
                    except Exception:
                        logging.debug("error while attempting to send match notification", exc_info=True)
                    for rec in cleaned:
                        logging.debug("cleaned record: %s", rec)
                    return True

                return True
            except Exception as e:
                last_exc = e
                logging.warning("POST to api2 failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
                time.sleep(1)

        logging.exception("all attempts to POST to api2 failed: %s", last_exc)
        return False
    except Exception:
        logging.exception("unexpected error in post_attendance_query")
        return False


def extract_course_records(response_json: Dict[str, Any], course_names: List[str]) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(response_json, dict):
        return None

    data = response_json.get("data") or response_json.get("result") or response_json
    if not isinstance(data, dict):
        return None

    lst = data.get("list")
    if not isinstance(lst, list):
        return None

    matches: List[Dict[str, Any]] = []
    normalized = [c.strip() for c in course_names if isinstance(c, str)]

    for item in lst:
        try:
            subj = item.get("subjectBean") or {}
            sname = subj.get("sName") or subj.get("sSimple") or ""
            sname = (sname or "").strip()
            if sname and any(sname == cn for cn in normalized):
                matches.append(item)
        except Exception:
            logging.debug("error while examining item for course match", exc_info=True)

    if not matches:
        return None
    return matches


def clean_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for item in records:
        try:
            subj = item.get("subjectBean", {})
            room = item.get("roomBean") or (item.get("classWaterBean") or {}).get("roomBean") or {}
            class_water = item.get("classWaterBean", {})
            teach = item.get("teachNameList") or ""
            cleaned.append({
                "course": subj.get("sName") or subj.get("sSimple"),
                "teacher": teach,
                "room": room.get("roomnum") if isinstance(room, dict) else None,
                "operdate": class_water.get("operdate"),
                "photo": class_water.get("photo"),
                "status": class_water.get("status"),
            })
        except Exception:
            logging.debug("error cleaning record", exc_info=True)
    return cleaned


# time-based matching moved to kq.matcher.match_records_by_time
