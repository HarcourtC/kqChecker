"""Generate weekly_schedule.ics atomically with optional backup.

Usage:
  python gen_weekly_ics.py --output weekly_schedule.ics --backup --minutes 90

This script uses kq.icsgen's load_weekly, load_periods and make_ics to build the
ICS text, writes it to a temporary file and then replaces the target file
atomically (os.replace). If --backup is given and the target exists, the old
file is copied to <output>.bak before replacement.
"""
from pathlib import Path
import argparse
import os
import shutil
from datetime import datetime

from kq.icsgen import load_weekly, load_periods, make_ics


def atomic_write(output_path: Path, text: str) -> None:
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    # Write tmp file
    tmp.write_text(text, encoding="utf-8")
    # Replace atomically
    os.replace(str(tmp), str(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly ICS atomically")
    parser.add_argument("--output", "-o", default="weekly_schedule.ics", help="Output ICS path")
    parser.add_argument("--backup", action="store_true", help="Keep a .bak of the previous ICS if it exists")
    parser.add_argument("--minutes", type=int, default=60, help="Default duration in minutes when period end not found")
    args = parser.parse_args()

    out = Path(args.output)
    try:
        events = load_weekly()
        periods = load_periods()
        ics_text = make_ics(events, periods, default_minutes=args.minutes)

        if args.backup and out.exists():
            bak = out.with_suffix(out.suffix + ".bak")
            try:
                shutil.copy2(out, bak)
                print(f"Backed up existing file to {bak}")
            except Exception as e:
                print(f"Warning: failed to create backup: {e}")

        atomic_write(out, ics_text)
        print(f"Generated ICS -> {out.resolve()}")
        return 0

    except Exception as e:
        print(f"ERROR: failed to generate ICS: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
