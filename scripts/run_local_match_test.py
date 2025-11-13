"""Run an offline time-based match test using a local saved api response and weekly_test.json.

This script imports kq.matcher and loads two JSON files from the repo, then runs
match_records_by_time for the date present in weekly_test.json and prints a
compact summary of matches.
"""

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path so package imports work when running this script directly
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT.resolve()))

from kq.matcher import match_records_by_time

resp_path = ROOT / "real_api_response_20251111T152425.json"
weekly_path = ROOT / "weekly_test.json"

if not weekly_path.exists():
    print("weekly_test.json not found:", weekly_path)
    raise SystemExit(1)

if resp_path.exists():
    resp = json.loads(resp_path.read_text(encoding="utf-8"))
else:
    # fallback: build a small synthetic response with operdate fields near the test events
    print("response file not found; using synthetic test response")
    resp = {
        "data": {
            "list": [
                {
                    "operdate": "2025-11-11 19:25:00",
                    "teachNameList": "Teacher X",
                    "subjectBean": {"sName": "Some Subject"},
                },
                {
                    "operdate": "2025-11-11 14:03:00",
                    "teachNameList": "Teacher B",
                    "subjectBean": {"sName": "Test Course B"},
                },
                {
                    "operdate": "2025-11-11 16:05:00",
                    "teachNameList": "Teacher A",
                    "subjectBean": {"sName": "Test Course A"},
                },
            ]
        }
    }
weekly = json.loads(weekly_path.read_text(encoding="utf-8"))

# infer a date prefix from weekly_test.json keys
sample_key = next(iter(weekly.keys()))
date_prefix = sample_key.split(" ")[0]

matches = match_records_by_time(
    resp,
    weekly,
    date_prefix=date_prefix,
    before_minutes=20,
    after_minutes=5,
    time_fields=("operdate", "watertime", "intime"),
)

total = sum(len(v) for v in matches.values())
print(f"Match summary for date {date_prefix}: total candidates = {total}")
for k, recs in matches.items():
    print(f"Event {k} -> {len(recs)} candidate(s)")
    for r in recs[:3]:
        # print a small sanitized snippet
        snippet = {
            "operdate": r.get("operdate") or r.get("watertime") or r.get("intime"),
            "teacher": r.get("teachNameList"),
            "subject": (
                (r.get("subjectBean") or {}).get("sName")
                if isinstance(r.get("subjectBean"), dict)
                else None
            ),
        }
        print("  ", snippet)

if total == 0:
    print(
        "\nNo time-based candidates found. If you expect matches, consider verifying the time fields in the saved response."
    )
else:
    print(
        "\nTime-based matching returned candidates; post_attendance_query should treat this as a success."
    )
