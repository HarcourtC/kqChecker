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
                    matched = extract_course_records(resp_json, courses)
                    if not matched:
                        logging.info("no matching attendance records found for courses=%s on %s", courses, date_str)
                        return False
                    cleaned = clean_records(matched)
                    logging.info("found %d matching attendance record(s)", len(cleaned))
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
