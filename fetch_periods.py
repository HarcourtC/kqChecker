"""Fetch periods.json from api3 and save it.

Usage examples:
  # use api3 from config.json
  python fetch_periods.py

  # override url and avoid saving (dry-run)
  python fetch_periods.py --url https://api.example.com/getPeriods --no-save

Default payload is set to the value you provided.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PAYLOAD = {"calendarBh": 606, "weekOrder": 10, "weekNum": ""}


def main():
    parser = argparse.ArgumentParser(
        description="Fetch periods.json from api3 and save to repo root"
    )
    parser.add_argument("--url", help="Override api3 URL (if not set in config.json)")
    parser.add_argument("--payload", help="JSON payload to POST (overrides default)")
    parser.add_argument(
        "--save",
        dest="save",
        action="store_true",
        help="Save returned JSON to periods.json (default)",
    )
    parser.add_argument(
        "--no-save", dest="save", action="store_false", help="Do not write periods.json"
    )
    parser.set_defaults(save=True)
    parser.add_argument(
        "--save-path", help="Custom save path for periods.json (optional)"
    )
    args = parser.parse_args()

    try:
        import kq.schedulegen as sg
    except Exception as e:
        print("Failed to import kq.schedulegen:", e, file=sys.stderr)
        return 2

    if args.payload:
        try:
            payload = json.loads(args.payload)
        except Exception as e:
            print("Invalid payload JSON:", e, file=sys.stderr)
            return 3
    else:
        payload = DEFAULT_PAYLOAD

    try:
        # fetch and (optionally) save
        save_path = (
            args.save_path
            if args.save and args.save_path
            else (None if not args.save else None)
        )
        # note: fetch_periods_from_api will default save path to repo root periods.json
        result = sg.fetch_periods_from_api(
            payload, url=args.url, save_path=args.save_path
        )
        print("Fetched periods JSON successfully.")
        # print a short summary
        if (
            isinstance(result, dict)
            and "data" in result
            and isinstance(result["data"], list)
        ):
            print(f"Items: {len(result['data'])}")
        else:
            print("Returned JSON shape:", type(result))
        return 0
    except Exception as e:
        print("Failed to fetch/save periods.json:", e, file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
