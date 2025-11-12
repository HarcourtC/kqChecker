"""Test script for match notification templates.

Usage:
  python scripts/test_match_notification.py        # render and print
  python scripts/test_match_notification.py --send # actually schedule send (uses config.json smtp)

By default this script only prints the rendered subject/body so it's safe to run locally.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from kq.config import load_config
from kq.notifier import send_miss_email_async


def load_cfg():
    cfg = load_config() or {}
    if not cfg:
        ex = ROOT / "config_example.json"
        if ex.exists():
            try:
                cfg = json.loads(ex.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
    return cfg


def render_match(cfg):
    notifs = (cfg or {}).get("notifications") or {}
    tpl_subj = notifs.get("match_subject")
    tpl_body = notifs.get("match_body")

    # sample context: courses and cleaned matches
    ctx = {
        "courses": ["高等数学(一)", "线性代数"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "matches": [
            {
                "operdate": "2025-11-12 08:55:00",
                "course": "高等数学(一)",
                "room": "教2楼-西403",
                "teacher": "张老师",
            },
            {
                "operdate": "2025-11-12 09:05:00",
                "course": "线性代数",
                "room": "教1楼-东201",
                "teacher": "李老师",
            },
        ],
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
            # if template expects {matches} as string, provide a simple join
            if isinstance(ctx.get("matches"), list):
                sd["matches"] = "\n".join(
                    [
                        f"- {m.get('operdate')} | {m.get('course')} | {m.get('room')} | {m.get('teacher')}"
                        for m in ctx["matches"]
                    ]
                )
            body = tpl_body.format_map(sd)
    except Exception:
        body = None

    if not subj:
        subj = (
            f"Attendance records found for {', '.join(ctx['courses'])} on {ctx['date']}"
        )
    if not body:
        try:
            mlines = []
            for m in ctx["matches"]:
                mlines.append(
                    f"- {m.get('operdate')} | {m.get('course')} | {m.get('room')} | {m.get('teacher')}"
                )
            body = "Attendance records detected:\n" + "\n".join(mlines)
        except Exception:
            body = "Attendance records were detected."

    return subj, body, ctx


if __name__ == "__main__":
    cfg = load_cfg()
    subj, body, ctx = render_match(cfg)
    print("SUBJECT:")
    print(subj)
    print("\nBODY:")
    print(body)

    if "--send" in sys.argv:
        print("\nScheduling send (async) using SMTP config in config.json...")
        ok = send_miss_email_async(cfg, subject=subj, body=body, context=ctx)
        print("Scheduled:", ok)
