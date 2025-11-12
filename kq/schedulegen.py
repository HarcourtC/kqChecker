"""Schedule generation helpers.

Provides functions to extract rows from API responses, build a period map from
periods.json and convert rows into a calendar mapping YYYY-MM-DD HH:MM:SS -> [courses].
"""

import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except Exception:  # pragma: no cover - optional runtime dependency
    requests = None
import argparse
import json
import time
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover - optional runtime dependency
    requests = None


def extract_rows(api_json: Any) -> List[Dict[str, Any]]:
    """Extract a list of record dicts from various API response shapes.

    Supports:
    - { "data": [ ... ] }
    - { "datas": { "xskcb": { "rows": [...] } } }
    - { "rows": [ ... ] }
    - Direct list (if caller passes the data list)
    """
    if isinstance(api_json, list):
        return api_json
    if not isinstance(api_json, dict):
        return []
    if isinstance(api_json.get("data"), list):
        return list(api_json.get("data") or [])
    datas = api_json.get("datas") or api_json.get("data") or api_json
    if isinstance(datas, dict):
        xskcb = datas.get("xskcb")
        if isinstance(xskcb, dict) and isinstance(xskcb.get("rows"), list):
            return list(xskcb.get("rows") or [])
    if isinstance(api_json.get("rows"), list):
        return list(api_json.get("rows") or [])
    return []


def build_period_map(periods_json: Dict[str, Any]) -> Dict[int, Dict[str, str]]:
    """Build a mapping from integer period (jc) to {'starttime','endtime'}.

    periods_json is expected to contain a 'data' array where each item has
    'jc', 'starttime', 'endtime'.
    """
    out: Dict[int, Dict[str, str]] = {}
    if not isinstance(periods_json, dict):
        return out
    data = periods_json.get("data") or []
    for item in data:
        jc = item.get("jc")
        try:
            ji = int(str(jc))
        except Exception:
            continue
        out[ji] = {"starttime": item.get("starttime"), "endtime": item.get("endtime")}
    return out


_JT_RE = re.compile(r"^(\d+)(?:-(\d+))?")


def parse_jt(jt_str: Optional[str]):
    if not jt_str:
        return None, None
    m = _JT_RE.match(str(jt_str).strip())
    if not m:
        return None, None
    try:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        return a, b
    except Exception:
        return None, None


def build_weekly_calendar(
    rows: List[Dict[str, Any]],
    period_map: Dict[int, Dict[str, str]],
    use_week_of_today: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Convert rows into a mapping YYYY-MM-DD HH:MM:SS -> [entry objects].

    Each entry object has keys: 'course', 'room', 'raw' (the original row dict).

    If use_week_of_today is True, dates are based on the current week (Monday start).
    """
    cal: Dict[str, List[Dict[str, Any]]] = {}
    if use_week_of_today:
        today = datetime.today().date()
        week_start = today - timedelta(days=today.weekday())
    else:
        week_start = None

    for r in rows:
        wk = r.get("accountWeeknum") or r.get("accountWeek") or r.get("week")
        try:
            wk_int = int(str(wk))
        except Exception:
            continue
        if wk_int == 0:
            wk_int = 7
        if wk_int < 1 or wk_int > 7:
            continue

        jt = r.get("accountJtNo") or r.get("accountJt") or r.get("jt") or ""
        jc_start, jc_end = parse_jt(jt)
        if jc_start is None:
            continue

        start_time = None
        if period_map and jc_start in period_map:
            start_time = period_map[jc_start].get("starttime")
        key_time = start_time if start_time else "00:00:00"

        course = (
            r.get("subjectSName")
            or r.get("subjectSSimple")
            or r.get("subjectSCode")
            or ""
        )
        # try to extract a room/location from common fields returned by different APIs
        room = None
        for room_key in ("roomName", "room", "classroom", "roomnum"):
            rv = r.get(room_key)
            if rv:
                room = rv
                break
        # api1 uses buildName + roomRoomnum in responses
        if not room:
            bn = r.get("buildName")
            rr = r.get("roomRoomnum")
            if bn or rr:
                room = f"{bn or ''} {rr or ''}".strip()
        # nested roomBean patterns
        if not room:
            rb = r.get("roomBean") or (r.get("classWaterBean") or {}).get("roomBean")
            if isinstance(rb, dict):
                room = rb.get("roomnum") or rb.get("roomname") or rb.get("name")
        if not course:
            continue

        if week_start:
            day = week_start + timedelta(days=(wk_int - 1))
        else:
            continue

        date_str = day.strftime("%Y-%m-%d")
        key = f"{date_str} {key_time}"
        # produce a structured entry so downstream can access course and room separately
        entry_obj = {
            "course": course,
            "room": room,
            "raw": r,
        }

        # keep backward-compatible fallback: if existing values are strings, convert them
        if key in cal:
            # avoid duplicates by course+room
            seen = {
                (e.get("course"), e.get("room")) if isinstance(e, dict) else (e, None)
                for e in cal[key]
            }
            tup = (entry_obj.get("course"), entry_obj.get("room"))
            if tup not in seen:
                cal[key].append(entry_obj)
        else:
            cal[key] = [entry_obj]

    return cal


def save_weekly(path, calendar_map):
    import json
    from pathlib import Path

    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(
        json.dumps(calendar_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # write tmp then move/replace into final path
    tmp.replace(p)


def fetch_from_api1(
    payload: Dict[str, Any],
    timeout: int = 10,
    retries: int = 2,
    periods_path: Optional[str] = None,
    use_week_of_today: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Post payload to api1 (from config.json), parse response and return calendar_map.

    - payload: dict to POST to api1
    - periods_path: optional path to periods.json; if None, will look for ../periods.json
    - returns calendar mapping (same shape as build_weekly_calendar output)
    """
    # local import to avoid circular imports at package import time
    try:
        from .config import load_config
    except Exception:
        # fallback to reading sibling config.json
        def load_config():
            p = Path(__file__).parent.parent / "config.json"
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}

    cfg = load_config()
    url = cfg.get("api1")
    headers = cfg.get("headers", {}) or {}

    if not url:
        raise RuntimeError("api1 not configured in config.json")

    if requests is None:
        raise RuntimeError("requests library not available; install requests")

    session = requests.Session()
    last_exc = None
    resp_json = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp_json = resp.json()
            break
        except Exception as e:
            last_exc = e
            time.sleep(1)

    if resp_json is None:
        raise last_exc or RuntimeError("failed to fetch from api1")

    rows = extract_rows(resp_json)

    # load periods.json
    if periods_path:
        ppath = Path(periods_path)
    else:
        ppath = Path(__file__).parent.parent / "periods.json"
    try:
        periods_json = json.loads(ppath.read_text(encoding="utf-8"))
    except Exception:
        periods_json = {}

    period_map = build_period_map(periods_json)
    cal = build_weekly_calendar(rows, period_map, use_week_of_today=use_week_of_today)
    return cal


def main(argv=None) -> int:
    """Command-line entry for schedulegen: generate `weekly.json` from API or sample.

    Mirrors the previous behavior of the repository-level script `get_weekly_json.py`.
    """
    parser = argparse.ArgumentParser(
        description="Generate weekly.json from API or sample data"
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Generate from sample.json (safe, offline)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write files; just print output"
    )
    parser.add_argument("--termNo", type=int, help="Override termNo for api1 payload")
    parser.add_argument("--week", type=int, help="Override week for api1 payload")
    parser.add_argument(
        "--save-payload",
        action="store_true",
        help="Save the provided termNo/week into config.json as api1_payload",
    )
    args = parser.parse_args(argv)

    ROOT = Path(__file__).parent.parent
    OUT = ROOT / "weekly.json"
    SAMPLE = ROOT / "sample.json"

    # load_config is available in kq.config
    try:
        from .config import load_config
    except Exception:

        def load_config():
            p = Path(__file__).parent.parent / "config.json"
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}

    if args.sample:
        if not SAMPLE.exists():
            print("sample.json not found")
            return 2
        s = json.loads(SAMPLE.read_text(encoding="utf-8"))
        rows = extract_rows(s)
        periods = {}
        periods_path = ROOT / "periods.json"
        if periods_path.exists():
            try:
                periods = json.loads(periods_path.read_text(encoding="utf-8"))
            except Exception:
                periods = {}
        period_map = build_period_map(periods)
        sched = build_weekly_calendar(rows, period_map)
    else:
        cfg = load_config()
        url = cfg.get("api1")
        if not url:
            print("api1 not configured in config.json; use --sample for testing")
            return 2

        api1_payload_cfg = cfg.get("api1_payload") if isinstance(cfg, dict) else {}
        term_no = (
            api1_payload_cfg.get("termNo")
            if isinstance(api1_payload_cfg, dict)
            else None
        )
        week_no = (
            api1_payload_cfg.get("week") if isinstance(api1_payload_cfg, dict) else None
        )

        # CLI overrides
        if getattr(args, "termNo", None) is not None:
            term_no = args.termNo
        if getattr(args, "week", None) is not None:
            week_no = args.week

        term_no = term_no or 606
        week_no = week_no or 10

        payload = {"termNo": int(term_no), "week": int(week_no)}

        # Optionally persist payload into config.json
        if getattr(args, "save_payload", False):
            cfg_path = Path(__file__).parent.parent / "config.json"
            try:
                cur = (
                    json.loads(cfg_path.read_text(encoding="utf-8"))
                    if cfg_path.exists()
                    else {}
                )
            except Exception:
                cur = {}
            cur["api1_payload"] = {"termNo": int(term_no), "week": int(week_no)}
            try:
                cfg_path.write_text(
                    json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"Saved api1_payload to {cfg_path}")
            except Exception as e:
                print("Failed to save api1_payload:", e)
        try:
            sched = fetch_from_api1(payload)
        except Exception as e:
            print("Failed to fetch from api1:", e)
            return 3

    out_text = json.dumps(sched, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(out_text)
        return 0

    try:
        save_weekly(OUT, sched)
        print("Wrote", OUT)
    except Exception:
        print("Failed to save weekly.json using kq.schedulegen")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def fetch_periods_from_api(
    payload: Dict[str, Any],
    url: Optional[str] = None,
    timeout: int = 10,
    retries: int = 2,
    save_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch periods.json-like JSON from the configured api3 or provided URL.

    Parameters:
    - payload: dict to POST
    - url: optional override for api3 URL from config.json
    - save_path: optional path to write the returned JSON; if None defaults to repo root 'periods.json'

    Returns the parsed JSON as a dict/list.
    """
    # lazy-load config to avoid circular imports at module import time
    try:
        from .config import load_config
    except Exception:

        def load_config():
            p = Path(__file__).parent.parent / "config.json"
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}

    cfg = load_config()
    api_url = url or (cfg.get("api3") if isinstance(cfg, dict) else None)
    if not api_url:
        raise RuntimeError(
            "api3 URL not configured in config.json and no --url provided"
        )

    if requests is None:
        raise RuntimeError("requests library not available; install requests")

    session = requests.Session()
    last_exc = None
    resp_json = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(api_url, json=payload, timeout=timeout)
            resp.raise_for_status()
            resp_json = resp.json()
            break
        except Exception as e:
            last_exc = e
            time.sleep(1)

    if resp_json is None:
        raise last_exc or RuntimeError("failed to fetch from api3")

    # save to disk if requested
    if save_path:
        out_path = Path(save_path)
    else:
        out_path = Path(__file__).parent.parent / "periods.json"

    try:
        tmp = out_path.with_name(out_path.name + ".tmp")
        tmp.write_text(
            json.dumps(resp_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(out_path)
    except Exception:
        # if saving fails, don't treat as fatal for callers that only wanted the JSON
        pass

    return resp_json
