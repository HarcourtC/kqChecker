#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

p = Path(__file__).parent.parent / "weekly_test.json"
parser = argparse.ArgumentParser()
parser.add_argument("--offset", type=int, default=2)
args = parser.parse_args()
now = datetime.now()
new_start = now + timedelta(minutes=args.offset)

try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    data = {}

keys = list(data.keys())
if keys:
    first_courses = data.pop(keys[0])
else:
    first_courses = ["Test Course A"]

newdata = {new_start.strftime("%Y-%m-%d %H:%M:%S"): first_courses}
for k in keys[1:]:
    newdata[k] = data[k]

p.write_text(json.dumps(newdata, ensure_ascii=False, indent=2), encoding="utf-8")
print("WROTE", p)
print("New first event:", list(newdata.keys())[0], first_courses)
