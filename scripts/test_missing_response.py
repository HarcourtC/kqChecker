"""Test the 'save missing POST response' behavior.

This script mocks requests.Session.post to return the local sample JSON
(`real_api_response_20251111T152425.json`) so we can exercise the code path
that saves the POST payload + response to the `debug_responses/` directory
when no match is found and `debug.save_missing_response` is enabled in
`config.json`.

Usage:
  # run with the python executable you use for the service (ykt env)
  python scripts/test_missing_response.py

The script will print where it saved the debug file (if any) and list the
created file(s).
"""
from pathlib import Path
import json
import logging
from datetime import datetime
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from kq.inquiry import post_attendance_query


def setup_logging():
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")


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
        logging.debug("MockSession.post called url=%s payload=%s headers=%s", url, json, headers)
        return MockResponse(self._data)


def main():
    setup_logging()

    # prefer an api2 (attendance waterList) sample if available
    sample_api2 = ROOT / 'sample_api2_response.json'
    sample_fallback = ROOT / 'real_api_response_20251111T152425.json'
    if sample_api2.exists():
        sample = sample_api2
    else:
        sample = sample_fallback

    if not sample.exists():
        print("sample response not found:", sample)
        return 2

    print("using sample:", sample.name)
    data = json.loads(sample.read_text(encoding='utf-8'))

    # monkeypatch requests.Session used inside post_attendance_query by
    # replacing requests.Session with our factory that returns MockSession.
    try:
        import requests
        # replace Session class/constructor with a lambda that returns MockSession
        requests.Session = lambda: MockSession(data)
    except Exception:
        print("requests not available in this Python environment. Install 'requests' and retry.")
        return 3

    # monkeypatch notifier to avoid sending real emails during tests
    try:
        import kq.notifier as notifier

        def _stub_send_miss_email_async(cfg, subject=None, body=None, context=None):
            logging.info("[TEST MODE] suppressed send_miss_email_async call; subject=%s", subject)
            return True

        notifier.send_miss_email_async = _stub_send_miss_email_async
        logging.debug("kq.notifier.send_miss_email_async monkeypatched to stub")
    except Exception:
        logging.debug("failed to monkeypatch notifier; continuing (be careful: real emails may be sent)", exc_info=True)

    # choose an event_time that exists in the sample date range
    event_time = datetime.now()

    # choose a course name that is unlikely to match sample records so the
    # 'no-match -> save debug' branch is taken. You can change this to a
    # course known to be absent/present in the sample.
    courses = ["NON_EXISTENT_COURSE_FOR_TEST"]

    # ensure debug dump dir is empty before running (so we can detect new files)
    from kq.config import load_config
    cfg = load_config() or {}
    dbg = (cfg.get('debug') or {})
    dump_dir = Path(__file__).parent.parent / (dbg.get('dump_dir') or 'debug_responses')
    dump_dir.mkdir(parents=True, exist_ok=True)

    before = set(p.name for p in dump_dir.glob('missing_*.json'))

    print("Running post_attendance_query (mocked). This will not send HTTP or email.")
    ok = post_attendance_query(event_time, courses=courses, pageSize=10, current=1, calendarBh="")
    print("post_attendance_query returned:", ok)

    after = set(p.name for p in dump_dir.glob('missing_*.json'))
    new = sorted(list(after - before))
    if new:
        print("Saved debug file(s):")
        for n in new:
            p = dump_dir / n
            print(" -", p)
            # show small preview
            try:
                txt = p.read_text(encoding='utf-8')
                print(txt[:1000])
            except Exception as e:
                print("  (failed to read file)", e)
    else:
        print("No new debug file created in", dump_dir)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
