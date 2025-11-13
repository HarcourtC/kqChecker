#!/usr/bin/env python3
"""Simulate api2 returning a 400-like JSON and exercise the error handler path.

This script will:
- monkeypatch requests.Session to return a MockResponse with JSON {code:400,...}
- monkeypatch kq.notifier.send_miss_email to a stub (avoid real email)
- call post_attendance_query for the '电子技术与系统' event and let the
  API400Error path be exercised; the error handler will save a debug dump.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from kq.error_handler import handle_api400
from kq.inquiry import API400Error, post_attendance_query


class MockResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class MockSession:
    def __init__(self, data):
        self._data = data

    def post(self, url, json=None, headers=None, timeout=None):
        print("MockSession.post called; returning simulated 200+code400 payload")
        return MockResponse(self._data)


def find_event(course_name: str):
    wk = ROOT / "weekly.json"
    raw = json.loads(wk.read_text(encoding="utf-8"))
    for k, v in raw.items():
        for item in v:
            if item.get("course") == course_name:
                try:
                    dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                return dt, v
    return None, None


def main():
    # prepare simulated API response with code==400
    fake = {
        "code": 400,
        "success": False,
        "data": None,
        "msg": "模拟: 未登录/需要重新登录",
    }

    # monkeypatch requests.Session used inside post_attendance_query
    try:
        import requests

        requests.Session = lambda: MockSession(fake)
    except Exception:
        print("requests not available; ensure environment has requests installed")
        return 2

    # stub out actual email sending to avoid real emails
    try:
        import kq.notifier as notifier

        def _stub_send_miss_email(cfg, subject=None, body=None, context=None):
            print("[TEST STUB] send_miss_email called; subject=", subject)
            return True

        notifier.send_miss_email = _stub_send_miss_email
        print("Monkeypatched kq.notifier.send_miss_email -> stub")
    except Exception:
        print("failed to monkeypatch notifier; aborting")
        return 3

    dt, entries = find_event("电子技术与系统")
    if not dt:
        print("event not found")
        return 4

    print("Running post_attendance_query for", dt, entries)
    try:
        ok = post_attendance_query(dt, courses=entries)
        print("post_attendance_query returned", ok)
        return 0
    except API400Error as e:
        print(
            "API400Error caught in test harness; delegating to handle_api400 (should save dump)"
        )
        try:
            from kq.config import load_config

            cfg = load_config() or {}
        except Exception:
            cfg = {}
        # call handler; it will attempt to send (stubbed) and then exit(1)
        try:
            handle_api400(cfg, e)
        except SystemExit as se:
            print("handle_api400 exited with", se.code)
            return int(se.code or 1)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
