#!/usr/bin/env python3
"""Generate an ICS file from weekly.json.

Usage:
    python generate_ics.py [-o weekly_schedule.ics] [--default-minutes 60]

Behavior:
 - Reads `weekly.json` for events (keys are "%Y-%m-%d %H:%M:%S").
 - Tries to read `periods.json` to determine matching period end time. If a period matches the event time, uses that period end as DTEND. Otherwise uses default minutes.
 - Writes an iCalendar file with one VEVENT per schedule entry. SUMMARY is the joined course names.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
import uuid

ROOT = Path(__file__).parent
WEEKLY = ROOT / "weekly.json"
PERIODS = ROOT / "periods.json"


def load_weekly(path: Path) -> list[tuple[datetime, list[str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
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


def load_periods(path: Path) -> list[tuple[str, str]]:
    # returns list of (starttime, endtime) strings like "08:00:00"
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


def find_period_end(periods: list[tuple[str, str]], event_dt: datetime) -> datetime | None:
    tstr = event_dt.strftime("%H:%M:%S")
    for st, et in periods:
        if st == tstr:
            # return datetime with same date and et time
            dtend = datetime.combine(event_dt.date(), datetime.strptime(et, "%H:%M:%S").time())
            return dtend
    return None


def format_dt(dt: datetime) -> str:
    # format as YYYYMMDDTHHMMSS (floating local time)
    return dt.strftime("%Y%m%dT%H%M%S")


def make_ics(events: list[tuple[datetime, list[str]]], periods: list[tuple[str, str]], default_minutes: int = 60) -> str:
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


def main() -> None:
    p = argparse.ArgumentParser(description="Generate ICS from weekly.json")
    p.add_argument("-o", "--output", default="weekly_schedule.ics", help="output ics file")
    p.add_argument("--default-minutes", type=int, default=60, help="default duration in minutes if no period matched")
    args = p.parse_args()

    events = load_weekly(WEEKLY)
    periods = load_periods(PERIODS)
    ics = make_ics(events, periods, default_minutes=args.default_minutes)
    out = Path(args.output)
    out.write_text(ics, encoding="utf-8")
    print(f"Wrote {out.resolve()} with {len(events)} events")


if __name__ == "__main__":
    main()
