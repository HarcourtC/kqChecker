"""Test script for startup notification templates.

Usage:
  python scripts/test_startup_notification.py        # render and print
  python scripts/test_startup_notification.py --send # actually schedule send (uses config.json smtp)

By default this script only prints the rendered subject/body so it's safe to run locally.
"""

import json
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from kq.config import load_config
from kq.notifier import send_miss_email_async


def load_cfg():
    cfg = load_config() or {}
    # fall back to example if real config missing
    if not cfg:
        ex = ROOT / "config_example.json"
        if ex.exists():
            try:
                cfg = json.loads(ex.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
    return cfg


def render_startup(cfg):
    notifs = (cfg or {}).get("notifications") or {}
    tpl_subj = notifs.get("startup_subject")
    tpl_body = notifs.get("startup_body")

    now = datetime.now()
    host = ""
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"

    ctx = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "host": host,
    }

    class _SafeDict(dict):
        def __missing__(self, key):
            return ""

    sd = _SafeDict()
    sd.update(ctx)

    subj = None
    body = None
    try:
        if tpl_subj:
            subj = tpl_subj.format_map(sd)
    except Exception:
        subj = None
    try:
        if tpl_body:
            body = tpl_body.format_map(sd)
    except Exception:
        body = None

    if not subj:
        subj = f"kqChecker started on {host} at {ctx['time']}"
    if not body:
        body = f"kqChecker scheduler started on {host} at {ctx['date']} {ctx['time']}.\nThis is an automated startup notification."

    return subj, body, ctx


if __name__ == "__main__":
    cfg = load_cfg()
    subj, body, ctx = render_startup(cfg)
    print("SUBJECT:")
    print(subj)
    print("\nBODY:")
    print(body)

    if "--send" in sys.argv:
        print("\nScheduling send (async) using SMTP config in config.json...")
        ok = send_miss_email_async(cfg, subject=subj, body=body, context=ctx)
        print("Scheduled:", ok)
