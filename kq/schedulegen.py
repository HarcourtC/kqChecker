"""Schedule generation helpers.

Provides functions to extract rows from API responses, build a period map from
periods.json and convert rows into a calendar mapping YYYY-MM-DD HH:MM:SS -> [courses].
"""
from typing import Dict, List, Any, Optional
import re
import json
from datetime import datetime, date, timedelta
from pathlib import Path
import time

try:
    import requests
except Exception:  # pragma: no cover - optional runtime dependency
    requests = None
from pathlib import Path
import time

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
    if isinstance(api_json.get('data'), list):
        return list(api_json.get('data') or [])
    datas = api_json.get('datas') or api_json.get('data') or api_json
    if isinstance(datas, dict):
        xskcb = datas.get('xskcb')
        if isinstance(xskcb, dict) and isinstance(xskcb.get('rows'), list):
            return list(xskcb.get('rows') or [])
    if isinstance(api_json.get('rows'), list):
        return list(api_json.get('rows') or [])
    return []


def build_period_map(periods_json: Dict[str, Any]) -> Dict[int, Dict[str, str]]:
    """Build a mapping from integer period (jc) to {'starttime','endtime'}.

    periods_json is expected to contain a 'data' array where each item has
    'jc', 'starttime', 'endtime'.
    """
    out: Dict[int, Dict[str, str]] = {}
    if not isinstance(periods_json, dict):
        return out
    data = periods_json.get('data') or []
    for item in data:
        jc = item.get('jc')
        try:
            ji = int(str(jc))
        except Exception:
            continue
        out[ji] = {
            'starttime': item.get('starttime'),
            'endtime': item.get('endtime')
        }
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


def build_weekly_calendar(rows: List[Dict[str, Any]], period_map: Dict[int, Dict[str, str]], use_week_of_today: bool = True) -> Dict[str, List[str]]:
    """Convert rows into a mapping YYYY-MM-DD HH:MM:SS -> [course names].

    If use_week_of_today is True, dates are based on the current week (Monday start).
    """
    cal: Dict[str, List[str]] = {}
    if use_week_of_today:
        today = datetime.today().date()
        week_start = today - timedelta(days=today.weekday())
    else:
        week_start = None

    for r in rows:
        wk = r.get('accountWeeknum') or r.get('accountWeek') or r.get('week')
        try:
            wk_int = int(str(wk))
        except Exception:
            continue
        if wk_int == 0:
            wk_int = 7
        if wk_int < 1 or wk_int > 7:
            continue

        jt = r.get('accountJtNo') or r.get('accountJt') or r.get('jt') or ''
        jc_start, jc_end = parse_jt(jt)
        if jc_start is None:
            continue

        start_time = None
        if period_map and jc_start in period_map:
            start_time = period_map[jc_start].get('starttime')
        key_time = start_time if start_time else '00:00:00'

        course = r.get('subjectSName') or r.get('subjectSSimple') or r.get('subjectSCode') or ''
        if not course:
            continue

        if week_start:
            day = week_start + timedelta(days=(wk_int - 1))
        else:
            continue

        date_str = day.strftime('%Y-%m-%d')
        key = f"{date_str} {key_time}"
        if key in cal:
            if course not in cal[key]:
                cal[key].append(course)
        else:
            cal[key] = [course]

    return cal


def save_weekly(path, calendar_map):
    import json
    from pathlib import Path
    p = Path(path)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(calendar_map, ensure_ascii=False, indent=2), encoding='utf-8')
    p.replace(tmp)


def fetch_from_api1(payload: Dict[str, Any], timeout: int = 10, retries: int = 2, periods_path: Optional[str] = None, use_week_of_today: bool = True) -> Dict[str, List[str]]:
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
            p = Path(__file__).parent.parent / 'config.json'
            try:
                return json.loads(p.read_text(encoding='utf-8'))
            except Exception:
                return {}

    cfg = load_config()
    url = cfg.get('api1')
    headers = cfg.get('headers', {}) or {}

    if not url:
        raise RuntimeError('api1 not configured in config.json')

    if requests is None:
        raise RuntimeError('requests library not available; install requests')

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
        raise last_exc or RuntimeError('failed to fetch from api1')

    rows = extract_rows(resp_json)

    # load periods.json
    if periods_path:
        ppath = Path(periods_path)
    else:
        ppath = Path(__file__).parent.parent / 'periods.json'
    try:
        periods_json = json.loads(ppath.read_text(encoding='utf-8'))
    except Exception:
        periods_json = {}

    period_map = build_period_map(periods_json)
    cal = build_weekly_calendar(rows, period_map, use_week_of_today=use_week_of_today)
    return cal
