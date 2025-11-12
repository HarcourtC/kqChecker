#!/usr/bin/env python3
import json
from pathlib import Path

from kq.config import load_config
from kq.notifier import send_miss_email

cfg = load_config()
wk = json.loads(Path("weekly_test.json").read_text(encoding="utf-8"))
first_key = next(iter(wk.keys()))
courses = wk[first_key]
date_str = first_key.split(" ")[0]

subject = f"Attendance missing for {', '.join(courses)} on {date_str}"
body = f"Automated attendance alert:\n\nCourses: {courses}\nDate: {date_str}\n\nThis is a test send of the attendance-missing notification."

print("Sending attendance notification now (synchronous) to configured recipients...")
ok = send_miss_email(cfg, subject, body)
print("send_miss_email returned", ok)
