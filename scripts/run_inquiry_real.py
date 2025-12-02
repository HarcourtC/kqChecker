"""Invoke kq.inquiry.post_attendance_query using the real `py_config.json` settings.

This script will:
- load `py_config.json` from the repo root (must exist)
- insert the repo root to `sys.path` so `kq` package imports work
- monkeypatch `kq.config.load_config` to return the loaded `py_config.json` dict
- call `post_attendance_query` with a sample event_time and optional course list

Run in the conda env that has network access and `requests` installed, for example:
  conda run -n kq_dev python scripts\run_inquiry_real.py

WARNING: This will perform a live network POST to the configured `api2` endpoint using
credentials present in `py_config.json`. Do not run unless you are authorized.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PY_CFG = ROOT / "py_config.json"

if not PY_CFG.exists():
    print(f"py_config.json not found at {PY_CFG}; aborting")
    sys.exit(2)

try:
    py_cfg = json.loads(PY_CFG.read_text(encoding="utf-8"))
except Exception as e:
    print("Failed to read py_config.json:", e)
    sys.exit(3)

# ensure local package import works
sys.path.insert(0, str(ROOT))

try:
    # import modules
    import kq.config as kqconfig
    import kq.inquiry as kqinquiry
    from kq.inquiry import post_attendance_query
except Exception as e:
    print("Failed to import kq modules:", e)
    sys.exit(4)

# monkeypatch load_config to return py_config contents
kqconfig.load_config = lambda: py_cfg
# also patch the name bound inside kq.inquiry (it imported load_config at module import time)
try:
    kqinquiry.load_config = lambda: py_cfg
except Exception:
    pass

# pick an event_time: use now
event_time = datetime.now()
print("Calling post_attendance_query with event_time:", event_time.isoformat())
try:
    # if you want to target specific course(s), change the list below
    courses = ["TEST_REAL_CALL"]
    ok = post_attendance_query(event_time, courses=courses, timeout=15, retries=1)
    print("post_attendance_query returned:", ok)
except Exception as e:
    # Avoid printing sensitive contents; show repr only
    print("post_attendance_query raised:", repr(e))
    sys.exit(5)

print("Done. If debug saving is enabled in config, check the configured dump_dir.")
