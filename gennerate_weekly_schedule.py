"""生成一周课程日历（周模式）

功能：
- 读取课表 JSON（示例在聊天中），从 records 中读取字段：
  - 星期：优先使用 `accountWeeknum`（代表星期几，1=星期一），若无再尝试 `week`。
  - 节次：使用 `accountJtNo`（例如 "7-8" 或 "3-4"），取起始节次作为开始节。
  - 课程名：使用 `subjectSName`、回退到 `subjectSSimple` 或 `subjectSCode`。
- 读取节次映射 JSON（包含 data 数组，元素含字段 jc/starttime/endtime），将 jc -> starttime 对照起来。
- 构建一周日历：键为 "星期X HH:MM:SS"（例如 "星期二 14:00:00"），值为该时段的课程名数组（去重）。
- 输出为 JSON 文件。

用法示例：
    python src.py --input sample.json --periods periods.json --output weekly.json
"""

import json
import argparse
import re
from typing import Dict, List
from datetime import datetime, date, timedelta
import os


def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_period_map(periods_json: dict) -> Dict[int, Dict[str, str]]:
    """从 periods JSON 的 data 列表构建 {jc: {starttime, endtime}} 映射"""
    out = {}
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


def parse_jt(jt_str: str):
    """解析类似 '7-8' 或 '5' 的节次字符串 -> (start, end) 或 (None,None)"""
    if not jt_str:
        return None, None
    jt_str = jt_str.strip()
    m = re.match(r"^(\d+)(?:-(\d+))?", jt_str)
    if not m:
        return None, None
    try:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        return a, b
    except Exception:
        return None, None


def weekday_cn_from_number(n: int) -> str:
    """1->星期一 ... 7->星期日，若不在范围返回空字符串"""
    names = {1: '星期一', 2: '星期二', 3: '星期三', 4: '星期四', 5: '星期五', 6: '星期六', 7: '星期日'}
    return names.get(n, '')


def extract_rows(api_json: dict) -> List[dict]:
    """从多种返回包装中提取实际记录数组。
    支持直接 data 数组或 datas.xskcb.rows 等格式。
    """
    if not isinstance(api_json, dict):
        return []
    # 优先：data 是数组
    if isinstance(api_json.get('data'), list):
        return api_json.get('data')
    # 兼容 datas.xskcb.rows
    datas = api_json.get('datas') or api_json.get('data') or api_json
    if isinstance(datas, dict):
        xskcb = datas.get('xskcb')
        if isinstance(xskcb, dict) and isinstance(xskcb.get('rows'), list):
            return xskcb.get('rows')
    # 直接 rows 字段
    if isinstance(api_json.get('rows'), list):
        return api_json.get('rows')
    # 退回空
    return []


def build_weekly_calendar(rows: List[dict], period_map: Dict[int, dict], use_week_of_today: bool = True) -> Dict[str, List[str]]:
    """构建周日历：键为 'YYYY-MM-DD HH:MM:SS'（基于本周），值为课程名列表（去重）。

    参数 use_week_of_today: 如果 True，则以当前日期所在的周为基准（周一为第一天）。
    """
    cal: Dict[str, List[str]] = {}

    # 计算本周的周一日期（如果使用本周）
    if use_week_of_today:
        today = datetime.today().date()
        week_start = today - timedelta(days=today.weekday())  # 周一
    else:
        week_start = None

    for r in rows:
        # 星期：优先 accountWeeknum，再尝试 week
        wk = r.get('accountWeeknum') or r.get('accountWeek') or r.get('week')
        try:
            wk_int = int(str(wk))
        except Exception:
            # 无法解析星期，跳过
            continue
        # 有些系统 0 或 7 表示周日，规范到 1..7
        if wk_int == 0:
            wk_int = 7
        if wk_int < 1 or wk_int > 7:
            continue

        jt = r.get('accountJtNo') or r.get('accountJt') or r.get('accountJtNo') or r.get('jt') or ''
        jc_start, jc_end = parse_jt(jt)
        if jc_start is None:
            continue

        # 查找节次对应的开始时间
        start_time = None
        if period_map and jc_start in period_map:
            start_time = period_map[jc_start].get('starttime')
        # 若没有映射，使用 00:00:00 作为占位（用户指定使用 00:00）
        key_time = start_time if start_time else '00:00:00'

        # 课程名
        course = r.get('subjectSName') or r.get('subjectSSimple') or r.get('subjectSCode') or ''
        if not course:
            continue

        # 计算具体日期：week_start + (wk_int-1) 天
        if week_start:
            day = week_start + timedelta(days=(wk_int - 1))
        else:
            # 如果未启用基于本周，则不生成具体日期，跳过
            continue

        date_str = day.strftime('%Y-%m-%d')
        key = f"{date_str} {key_time}"
        if key in cal:
            if course not in cal[key]:
                cal[key].append(course)
        else:
            cal[key] = [course]

    return cal


def group_by_weekday(calendar_map: Dict[str, List[str]]) -> Dict[str, Dict[str, List[str]]]:
    """把键 '星期X HH:MM:SS' 转换为 { '星期X': { 'HH:MM:SS': [courses] } }"""
    out: Dict[str, Dict[str, List[str]]] = {}
    for key, courses in calendar_map.items():
        parts = key.split(None, 1)
        if len(parts) == 2:
            weekday, time_part = parts[0], parts[1]
        else:
            # 无法拆分，放到 '其他' 键
            weekday, time_part = '其他', key
        # 如果 time_part 包含多余说明（例如 '节7'），保留原样
        if weekday not in out:
            out[weekday] = {}
        if time_part in out[weekday]:
            for c in courses:
                if c not in out[weekday][time_part]:
                    out[weekday][time_part].append(c)
        else:
            out[weekday][time_part] = list(courses)
    return out


def main():
    parser = argparse.ArgumentParser(description='生成周模式课程日历：YYYY-MM-DD HH:MM:SS -> [课程名]')
    parser.add_argument('--input', '-i', help='课表 JSON 文件（默认 sample.json）', default='sample.json')
    parser.add_argument('--periods', '-p', help='节次映射 JSON 文件（默认 periods.json）', default='periods.json')
    parser.add_argument('--output', '-o', default='weekly.json', help='输出文件路径，默认 weekly.json')
    args = parser.parse_args()

    # 强制要求两个文件存在，否则直接报错退出
    if not os.path.isfile(args.input):
        print(f'错误：未找到课表文件 {args.input}，请在当前目录放入或通过 --input 指定')
        raise SystemExit(1)
    if not os.path.isfile(args.periods):
        print(f'错误：未找到节次映射文件 {args.periods}，请在当前目录放入或通过 --periods 指定')
        raise SystemExit(1)

    api_json = load_json(args.input)
    periods_json = load_json(args.periods)

    rows = extract_rows(api_json)
    period_map = build_period_map(periods_json)

    cal = build_weekly_calendar(rows, period_map)

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)

    print(f'已写入 {args.output}，共 {len(cal)} 条时段')


if __name__ == '__main__':
    main()
