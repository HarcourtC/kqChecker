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
    # atomically move tmp -> target
    tmp.replace(p)


def fetch_periods_from_api(payload: Dict[str, Any], url: Optional[str] = None, timeout: int = 10, retries: int = 2, save_path: Optional[str] = None) -> Dict[str, Any]:
    """Fetch periods data from an API and save as periods.json.

    - payload: JSON serializable dict to POST
    - url: optional URL to POST to; if None, will try to read 'api3' from config.json
    - save_path: optional path to write the resulting periods JSON; default is repo root 'periods.json'

    Returns the parsed JSON object on success. Raises RuntimeError on failure.
    """
    try:
        from .config import load_config
    except Exception:
        def load_config():
            p = Path(__file__).parent.parent / 'config.json'
            try:
                return json.loads(p.read_text(encoding='utf-8'))
            except Exception:
                return {}

    cfg = load_config()
    req_url = url or cfg.get('api3')
    headers = cfg.get('headers', {}) or {}

    if not req_url:
        raise RuntimeError('api3 URL not configured (pass url or set api3 in config.json)')

    if requests is None:
        raise RuntimeError('requests library not available; install requests')

    session = requests.Session()
    last_exc = None
    resp_json = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(req_url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp_json = resp.json()
            break
        except Exception as e:
            last_exc = e
            time.sleep(1)

    if resp_json is None:
        raise last_exc or RuntimeError('failed to fetch periods from api3')

    # normalize the response into expected format
    norm = normalize_periods(resp_json)

    # Determine save path
    if save_path:
        p = Path(save_path)
    else:
        p = Path(__file__).parent.parent / 'periods.json'

    # Write atomically (save normalized data)
    try:
        tmp = p.with_name(p.name + '.tmp')
        tmp.write_text(json.dumps(norm, ensure_ascii=False, indent=2), encoding='utf-8')
        # atomically move tmp -> target
        tmp.replace(p)
    except Exception as e:
        # writing failure is non-fatal for returning data, but we surface error
        raise RuntimeError(f'failed to save periods.json: {e}')

    return norm


def normalize_periods(raw: Any) -> Dict[str, Any]:
    """Normalize various periods API shapes into project format:
    {"data": [{"jc": int, "starttime": "HH:MM:SS", "endtime": "HH:MM:SS"}, ...]}

    Supports common shapes:
    - {'data': [...]}
    - direct list of items
    - items where 'jc' may be string (will be int-converted)
    """
    out = {"data": []}
    if isinstance(raw, dict) and isinstance(raw.get('data'), list):
        items = raw.get('data')
    elif isinstance(raw, list):
        items = raw
    else:
        # try other common wrappers
        items = None
        if isinstance(raw, dict):
            for key in ('rows', 'result', 'datas'):
                v = raw.get(key)
                if isinstance(v, list):
                    items = v
                    break
            if items is None:
                # maybe raw contains nested dict with list under xskcb.rows
                datas = raw.get('datas') or raw.get('data')
                if isinstance(datas, dict):
                    x = datas.get('xskcb')
                    if isinstance(x, dict) and isinstance(x.get('rows'), list):
                        items = x.get('rows')

    if not isinstance(items, list):
        return out

    for it in items:
        try:
            jc = it.get('jc') if isinstance(it, dict) else None
            if jc is None:
                # try other keys
                jc = it.get('accountJt') if isinstance(it, dict) else None
            ji = int(str(jc)) if jc is not None else None
            st = None
            et = None
            if isinstance(it, dict):
                st = it.get('starttime') or it.get('startTime') or it.get('beginTime')
                et = it.get('endtime') or it.get('endTime') or it.get('finishTime')
            if ji is None or not st or not et:
                continue
            out['data'].append({
                'jc': ji,
                'starttime': str(st),
                'endtime': str(et)
            })
        except Exception:
            continue

    return out
