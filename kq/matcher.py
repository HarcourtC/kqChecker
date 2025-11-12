"""Time-based matching helpers for attendance records."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence


def match_records_by_time(
    response_json: Dict[str, Any],
    weekly: Dict[str, List[str]],
    date_prefix: Optional[str] = None,
    before_minutes: int = 20,
    after_minutes: int = 5,
    time_fields: Sequence[str] = ("watertime", "intime"),
) -> Dict[str, List[Dict[str, Any]]]:
    """Match attendance records to weekly schedule by time window.

    Args:
        response_json: raw JSON returned by api2.
        weekly: mapping of "YYYY-MM-DD HH:MM:SS" -> [course names].
        date_prefix: date string like '2025-11-11' to select which weekly keys to match. If None,
            function will attempt to infer from weekly keys (useful when weekly contains only one date).
        before_minutes: minutes before course start to include.
        after_minutes: minutes after course start to include.
        time_fields: list of possible timestamp fields in a record to try (ordered).

    Returns:
        dict mapping weekly key (same string as in `weekly`) to list of matching raw records (may be empty).
    """

    matches: Dict[str, List[Dict[str, Any]]] = {}
    if not isinstance(weekly, dict):
        return matches

    # determine date prefix if not provided
    if date_prefix is None:
        # try to infer a common date from weekly keys
        if weekly:
            sample = next(iter(weekly.keys()))
            date_prefix = sample.split(" ")[0]
        else:
            return matches

    before = timedelta(minutes=before_minutes)
    after = timedelta(minutes=after_minutes)

    # build course times
    course_times = []  # tuples (key_str, datetime, course_name)
    for k, v in weekly.items():
        if not isinstance(k, str):
            continue
        if not k.startswith(date_prefix):
            continue
        try:
            dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        for course_name in v:
            if isinstance(course_name, str):
                matches.setdefault(k, [])
                course_times.append((k, dt, course_name))

    # extract records list from response_json
    records: List[Dict[str, Any]] = []
    if isinstance(response_json, dict):
        data = response_json.get("data") or response_json
        if isinstance(data, dict):
            lst = data.get("list") or data.get("records")
            if isinstance(lst, list):
                records = lst
        elif isinstance(data, list):
            records = data

    def parse_time_from_record(rec: Dict[str, Any]) -> Optional[datetime]:
        for f in time_fields:
            t = rec.get(f)
            if not t:
                continue
            try:
                return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
        return None

    # match
    for key_str, course_dt, course_name in course_times:
        for rec in records:
            rt = parse_time_from_record(rec)
            if rt is None:
                continue
            if (course_dt - before) <= rt <= (course_dt + after):
                matches.setdefault(key_str, []).append(rec)

    return matches
