"""查询模块：从 `config.json` 读取 `api2` 和 `headers`，向 `api2` 发送 POST 请求并返回响应（JSON 或文本）。

当前实现：
- 使用 `requests` 做 POST（需要在环境中安装 requests）。
- 简单的重试与超时处理。
- 不做数据清洗（由用户后续提供清洗规则）。
"""
from pathlib import Path
import json
import logging
import time
from typing import Any, Dict, Optional, List

try:
    import requests
except Exception:  # pragma: no cover - run-time dependency
    requests = None


CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> Dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("failed to load config.json")
        return {}


def post_attendance_query(event_time, courses=None, pageSize: int = 10, current: int = 1, calendarBh: str = "", timeout: int = 10, retries: int = 2, extra_headers: Optional[Dict[str, str]] = None) -> bool:
    """为考勤查询构造载荷并发送请求。

    - event_time: datetime 对象，函数会使用其日期作为 startdate 和 enddate。
    - courses: 可选，当前不会被直接放入 payload（后端接口按日期返回考勤列表），但保留以便记录或将来扩展。
    - extra_headers: 可选 dict，用来临时覆盖或补充 config.json 中的 headers。

    返回 post_api2 的解析结果或 None。
    """
    from datetime import datetime

    if not isinstance(event_time, datetime):
        logging.warning("post_attendance_query: event_time should be datetime, got %s", type(event_time))

    date_str = event_time.strftime("%Y-%m-%d")
    payload = {
        "calendarBh": calendarBh,
        "startdate": date_str,
        "enddate": date_str,
        "pageSize": pageSize,
        "current": current,
    }

    # load base headers and merge extra_headers if provided
    cfg = load_config()
    base_headers = cfg.get("headers", {}) or {}
    headers = base_headers.copy()
    if extra_headers:
        headers.update(extra_headers)

    # if environment token present, prefer it (already handled in post_api2 but ensure present)
    import os
    env_token = os.environ.get("KQ_TOKEN") or os.environ.get("SYNJONES_AUTH")
    if env_token:
        if env_token.lower().startswith("bearer "):
            headers["synjones-auth"] = env_token
        else:
            headers["synjones-auth"] = f"bearer {env_token}"

    # call the lower-level sender using merged headers by injecting into config temporarily
    # to reuse post_api2 logic, pass headers via extra key in payload (backwards-compatible)
    # but better: call requests directly here to provide explicit headers
    try:
        # Use requests directly to honor headers merging.
        if requests is None:
            logging.error("requests library not available. Install via 'pip install requests'")
            return False

        url = cfg.get("api2")
        if not url:
            logging.error("api2 URL not configured in config.json")
            return False

        session = requests.Session()
        last_exc = None
        for attempt in range(retries + 1):
            try:
                logging.debug("POST %s attempt %d payload=%s headers=%s", url, attempt + 1, payload, headers)
                resp = session.post(url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
                try:
                    resp_json = resp.json()
                except ValueError:
                    logging.warning("api2 returned non-json response; returning text")
                    return False

                # 尝试从响应中提取与课程名匹配的记录（如果 courses 提供）
                if courses:
                    matched = extract_course_records(resp_json, courses)
                    if not matched:
                        logging.info("no matching attendance records found for courses=%s on %s", courses, date_str)
                        return False
                    # 数据清洗：提取我们关心的字段集合并记录（内部使用）
                    cleaned = clean_records(matched)
                    logging.info("found %d matching attendance record(s)", len(cleaned))
                    # 将清洗后的记录记录到日志（可调整为写文件/数据库）
                    for rec in cleaned:
                        logging.debug("cleaned record: %s", rec)
                    return True

                # 如果未传入 courses，则仅表示请求成功但没有进行匹配
                return True
            except Exception as e:
                last_exc = e
                logging.warning("POST to api2 failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
                time.sleep(1)

        logging.exception("all attempts to POST to api2 failed: %s", last_exc)
        return False
    except Exception:
        logging.exception("unexpected error in post_attendance_query")
        return False


def clean_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把原始匹配记录清洗成更小、更易用的映射列表。

    每条记录提取：课程名(sName), 教师(teachNameList), 教室(roomnum), 操作时间(operdate), 照片(photo), 状态(status)
    """
    cleaned: List[Dict[str, Any]] = []
    for item in records:
        try:
            subj = item.get("subjectBean", {})
            room = item.get("roomBean") or (item.get("classWaterBean") or {}).get("roomBean") or {}
            class_water = item.get("classWaterBean", {})
            teach = item.get("teachNameList") or ""
            cleaned.append({
                "course": subj.get("sName") or subj.get("sSimple"),
                "teacher": teach,
                "room": room.get("roomnum") if isinstance(room, dict) else None,
                "operdate": class_water.get("operdate"),
                "photo": class_water.get("photo"),
                "status": class_water.get("status"),
            })
        except Exception:
            logging.debug("error cleaning record", exc_info=True)
    return cleaned


def extract_course_records(response_json: Dict[str, Any], course_names: List[str]) -> Optional[List[Dict[str, Any]]]:
    """从 API 响应中提取与 course_names 列表匹配的记录。

    - response_json: API 原始解析后的 JSON 对象
    - course_names: 要匹配的课程名列表（可能包含中文完整名）

    返回匹配记录的列表（可能包含多个），如果没有匹配则返回 None。
    匹配逻辑：检查每个 item 的 subjectBean.sName 或 subjectBean.sSimple 是否等于任一课程名。
    """
    if not isinstance(response_json, dict):
        logging.debug("extract_course_records: response is not a dict")
        return None

    data = response_json.get("data") or response_json.get("result") or response_json
    if not isinstance(data, dict):
        logging.debug("extract_course_records: data field missing or not dict")
        return None

    lst = data.get("list")
    if not isinstance(lst, list):
        logging.debug("extract_course_records: list field missing or not list")
        return None

    matches: List[Dict[str, Any]] = []
    # normalize course names for comparison
    normalized = [c.strip() for c in course_names if isinstance(c, str)]

    for item in lst:
        try:
            subj = item.get("subjectBean") or {}
            sname = subj.get("sName") or subj.get("sSimple") or ""
            sname = (sname or "").strip()
            if sname and any(sname == cn for cn in normalized):
                matches.append(item)
        except Exception:
            logging.debug("error while examining item for course match", exc_info=True)

    if not matches:
        return None
    return matches
