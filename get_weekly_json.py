"""Fetch weekly schedule and write `weekly.json` for the project.

Supports three modes:
 - --api : fetch from config.json's api1 (default behavior if no flags)
 - --sample : generate weekly.json from sample.json (safe offline smoke-test)
 - --dry-run : don't write files, just print what would be written

The script writes atomically and can keep a .bak of previous weekly.json.
"""
from pathlib import Path
import json
import argparse
import os
import shutil
from datetime import datetime, timedelta
import importlib

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"
OUT = ROOT / "weekly.json"
SAMPLE = ROOT / "sample.json"


def load_config():
    if not CONFIG.exists():
        return {}
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_sample():
    if not SAMPLE.exists():
        return None
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


# fallback parsing removed; schedulegen is the canonical parser


# saving is delegated to kq.schedulegen.save_weekly


def main():
    parser = argparse.ArgumentParser(description="Generate weekly.json from API or sample data")
    parser.add_argument("--sample", action="store_true", help="Generate from sample.json (safe, offline)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; just print output")
    args = parser.parse_args()

    # require schedulegen as the canonical parser/saver
    try:
        sg = importlib.import_module('kq.schedulegen')
    except Exception as e:
        print('Required module kq.schedulegen not available:', e)
        return 3

    if args.sample:
        s = load_sample()
        if s is None:
            print("sample.json not found")
            return 2
        # use schedulegen to parse sample format
        rows = sg.extract_rows(s)
        periods = {}
        periods_path = ROOT / 'periods.json'
        if periods_path.exists():
            periods = json.loads(periods_path.read_text(encoding='utf-8'))
        period_map = sg.build_period_map(periods)
        sched = sg.build_weekly_calendar(rows, period_map)
    else:
    # Default: try api1 from config.json using POST with payload {termNo, week}
        cfg = load_config()
        url = cfg.get("api1")
        headers = cfg.get("headers") or {}
        if not url:
            print("api1 not configured in config.json; use --sample for testing")
            return 2

        # allow overriding term/week from CLI or config.json
        api1_payload_cfg = cfg.get("api1_payload") if isinstance(cfg, dict) else {}
        # allow CLI to override config values; fall back to defaults
        term_no = getattr(args, 'termNo', None) or (api1_payload_cfg.get('termNo') if isinstance(api1_payload_cfg, dict) else None) or 606
        week_no = getattr(args, 'week', None) or (api1_payload_cfg.get('week') if isinstance(api1_payload_cfg, dict) else None) or 10

        # normalize headers to strings
        headers = {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in headers.items()}

        import requests
        payload = {"termNo": int(term_no), "week": int(week_no)}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print("Failed to POST to api1:", e)
            return 3

        rows = sg.extract_rows(data)
        periods = {}
        periods_path = ROOT / 'periods.json'
        if periods_path.exists():
            periods = json.loads(periods_path.read_text(encoding='utf-8'))
        period_map = sg.build_period_map(periods)
        sched = sg.build_weekly_calendar(rows, period_map)

    out_text = json.dumps(sched, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(out_text)
        return 0

    # save via schedulegen to centralize file handling
    try:
        sg.save_weekly(OUT, sched)
        print("Wrote", OUT)
    except Exception:
        print("Failed to save weekly.json using kq.schedulegen")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
