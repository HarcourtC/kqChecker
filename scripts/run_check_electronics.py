#!/usr/bin/env python3
"""Run one attendance check for the '电子技术与系统' event found in weekly.json.

This script loads the weekly schedule, finds the first matching event for the
course name, and calls `post_attendance_query` with the event time and entries.
If an API400Error is raised, it delegates handling to `kq.error_handler.handle_api400`
so the real alert/save/exit flow is exercised (as in the scheduler).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from kq.error_handler import handle_api400
from kq.inquiry import API400Error, post_attendance_query


def find_event(course_name: str):
    wk = ROOT / "weekly.json"
    if not wk.exists():
        raise SystemExit("weekly.json not found")
    raw = json.loads(wk.read_text(encoding="utf-8"))
    for k, v in raw.items():
        for item in v:
            if item.get("course") == course_name:
                # parse datetime
                try:
                    dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                return dt, v
    return None, None


def main():
    course = "电子技术与系统"
    dt, entries = find_event(course)
    if not dt:
        print("event not found for", course)
        return 2

    print("Found event:", dt.isoformat(), "entries=", entries)
    try:
        ok = post_attendance_query(dt, courses=entries)
        print("post_attendance_query returned", ok)
        return 0
    except API400Error as e:
        print("API400Error raised; delegating to error_handler")
        cfg = None
        try:
            from kq.config import load_config

            cfg = load_config() or {}
        except Exception:
            cfg = {}
        handle_api400(cfg, e)
        # handle_api400 should sys.exit; if it returns, return non-zero
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
