import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# local query module (sends POST to api2 using headers from config.json)
import InquryClassWater as inquiry


SCHEDULE_FILE = Path(__file__).parent / "weekly.json"
LOG_FILE = Path(__file__).parent / "attendance.log"


def setup_logging() -> None:
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s [%(levelname)s] %(message)s",
		handlers=[
			logging.FileHandler(LOG_FILE, encoding="utf-8"),
			logging.StreamHandler(),
		],
	)


def load_schedule(path: Path = SCHEDULE_FILE) -> List[Tuple[datetime, List[str]]]:
	"""从 JSON 文件读取日程并返回 (开始时间, [课程名...]) 的列表。

	支持时间格式："%Y-%m-%d %H:%M:%S"。任何无法解析的条目会被跳过并记录。
	"""
	if not path.exists():
		logging.warning("schedule file not found: %s", path)
		return []

	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except Exception as e:
		logging.exception("failed to read schedule file: %s", e)
		return []

	events: List[Tuple[datetime, List[str]]] = []
	for k, v in raw.items():
		try:
			dt = datetime.strptime(k, "%Y-%m-%d %H:%M:%S")
		except Exception:
			logging.warning("unrecognized datetime format, skipping: %s", k)
			continue
		if not isinstance(v, list):
			logging.warning("unexpected value for %s, expected list, got %s", k, type(v))
			continue
		events.append((dt, v))

	events.sort(key=lambda x: x[0])
	return events


def check_attendance(event_time: datetime, courses: List[str]) -> None:
	"""占位函数：在课程开始前 5 分钟被调用以查询考勤状态。

	TODO: 将来替换为实际的查询实现（由用户提供）。
	当前行为：记录将要查询的课程和时间。
	"""
	logging.info("checking attendance for %s at %s", courses, event_time.isoformat())

	try:
		# 使用 Inqury 模块内的便捷方法构造并发送考勤查询请求（会把 startdate/enddate 设为课程当日）
		result = inquiry.post_attendance_query(event_time, courses=courses)
		if result is None:
			logging.warning("no response or error when querying attendance for %s", courses)
		else:
			logging.info("attendance query result for %s: %s", courses, result)
			# TODO: 调用数据清洗/解析逻辑（用户将提供规则）
	except Exception:
		logging.exception("unexpected error while querying attendance for %s", courses)


def scheduler_loop(poll_interval: int = 30) -> None:
	"""持续运行的调度循环。

	- 每 poll_interval 秒重新加载 `weekly.json`。
	- 对于每个事件，如果当前时间 >= (start_time - 5min) 且尚未处理，则调用 check_attendance。
	"""
	processed = set()  # store event_time.isoformat() strings we've handled

	logging.info("scheduler started, watching %s", SCHEDULE_FILE)

	while True:
		try:
			now = datetime.now()
			events = load_schedule()

			for start_dt, courses in events:
				key = f"{start_dt.isoformat()}|{','.join(courses)}"
				if key in processed:
					continue

				check_time = start_dt - timedelta(minutes=5)

				# 如果现在已经过了课程开始时间，则跳过（太迟了）
				if now >= start_dt:
					logging.debug("event %s already started, skipping", start_dt)
					processed.add(key)
					continue

				# 如果到了或超过预检时间但未到上课时间，触发检查
				if check_time <= now < start_dt:
					logging.info("triggering attendance check for %s (starts at %s)", courses, start_dt)
					try:
						check_attendance(start_dt, courses)
					except Exception:
						logging.exception("error while checking attendance for %s", start_dt)
					processed.add(key)

			# Sleep and then re-evaluate. 如果文件更新，新的事件会被加载并处理。
			time.sleep(poll_interval)

		except KeyboardInterrupt:
			logging.info("scheduler received KeyboardInterrupt, exiting")
			break
		except Exception:
			logging.exception("unexpected error in scheduler loop")
			time.sleep(poll_interval)


def main() -> None:
	setup_logging()
	logging.info("attendance scheduler starting up")

	# 后台线程运行调度器，这样 main 可以扩展做其它事情（或简单等待）。
	t = threading.Thread(target=scheduler_loop, name="scheduler", daemon=True)
	t.start()

	try:
		# 主线程保持运行，守护子线程。按 Ctrl+C 停止。
		while t.is_alive():
			t.join(timeout=1)
	except KeyboardInterrupt:
		logging.info("received Ctrl+C, shutting down")


if __name__ == "__main__":
	main()