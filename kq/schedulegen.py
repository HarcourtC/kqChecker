"""Schedule generation helpers.

Provides functions to extract rows from API responses, build a period map from
periods.json and convert rows into a calendar mapping YYYY-MM-DD HH:MM:SS -> [courses].
"""
from typing import Dict, List, Any, Optional
import re
import json
from datetime import datetime, date, timedelta


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
