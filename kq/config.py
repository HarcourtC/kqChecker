from pathlib import Path
import json
from typing import Any, Dict

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def load_config() -> Dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
