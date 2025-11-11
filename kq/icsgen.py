"""ICS generation utilities."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from typing import List, Tuple

ROOT = Path(__file__).parent.parent
WEEKLY = ROOT / "weekly.json"
PERIODS = ROOT / "periods.json"


def load_weekly(path: Path = WEEKLY) -> List[Tuple[datetime, List[str]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    events = []
    for k, v in raw.items():
        try:
            dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if isinstance(v, list):
            events.append((dt, v))
    events.sort(key=lambda x: x[0])
    return events


def load_periods(path: Path = PERIODS) -> List[Tuple[str, str]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data") if isinstance(raw, dict) else raw
    periods = []
    if isinstance(data, list):
        for p in data:
            st = p.get("starttime")
            et = p.get("endtime")
            if st and et:
                periods.append((st, et))
    return periods


def find_period_end(periods: List[Tuple[str, str]], event_dt: datetime) -> datetime | None:
    tstr = event_dt.strftime("%H:%M:%S")
    for st, et in periods:
        if st == tstr:
            dtend = datetime.combine(event_dt.date(), datetime.strptime(et, "%H:%M:%S").time())
            return dtend
    return None


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def make_ics(events: List[Tuple[datetime, List[str]]], periods: List[Tuple[str, str]], default_minutes: int = 60) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//kqChecker//GenerateICS//EN",
    ]
    for dtstart, courses in events:
        dtend = find_period_end(periods, dtstart)
        if dtend is None:
            dtend = dtstart + timedelta(minutes=default_minutes)
        uid = f"{uuid.uuid4()}"
        summary = ", ".join(courses)
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{format_dt(datetime.now())}",
            f"DTSTART:{format_dt(dtstart)}",
            f"DTEND:{format_dt(dtend)}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def generate(output: str = "weekly_schedule.ics", default_minutes: int = 60) -> str:
    events = load_weekly()
    periods = load_periods()
    ics = make_ics(events, periods, default_minutes=default_minutes)
    out = Path(output)
    out.write_text(ics, encoding="utf-8")
    return str(out.resolve())

