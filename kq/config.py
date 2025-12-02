import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Type

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

# module-level caches
_CACHED_CONFIG: Optional[Dict[str, Any]] = None
_CACHED_MODEL: Optional[object] = None


def _apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment-variable overrides for common secret fields.

    This keeps backward compatibility while allowing secrets to be supplied
    via environment variables in production.
    """
    try:
        headers = cfg.get("headers") or {}
        v = os.environ.get("KQ_SYNJONES_AUTH")
        if v:
            headers["synjones-auth"] = v
        cfg["headers"] = headers

        smtp = cfg.get("smtp") or {}
        sp = os.environ.get("KQ_SMTP_PASSWORD")
        if sp:
            smtp["password"] = sp
        su = os.environ.get("KQ_SMTP_USERNAME")
        if su:
            smtp["username"] = su
        sf = os.environ.get("KQ_SMTP_FROM")
        if sf:
            smtp["from"] = sf
        cfg["smtp"] = smtp
    except Exception:
        pass
    return cfg


# Optional pydantic model for validated config
# Declare variable upfront so mypy sees a stable type (Optional[type])
ConfigModel: Optional[Type[Any]] = None

try:
    from pydantic import BaseModel, Field

    class _PydanticConfigModel(BaseModel):
        api1: Optional[str] = None
        api2: Optional[str] = None
        api3: Optional[str] = None
        headers: Dict[str, Any] = Field(default_factory=dict)
        smtp: Dict[str, Any] = Field(default_factory=dict)
        notifications: Dict[str, Any] = Field(default_factory=dict)
        debug: Dict[str, Any] = Field(default_factory=dict)
        api1_payload: Dict[str, Any] = Field(default_factory=dict)

    ConfigModel = _PydanticConfigModel
except Exception:
    ConfigModel = None


def load_config(refresh: bool = False) -> Dict[str, Any]:
    """Load and return configuration as a plain dict.

    If `pydantic` is available, the configuration will also be validated and
    made available via `get_config_model()`.
    """
    global _CACHED_CONFIG, _CACHED_MODEL
    if _CACHED_CONFIG is not None and not refresh:
        return _CACHED_CONFIG

    raw: Dict[str, Any] = {}
    try:
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}

    cfg = raw if isinstance(raw, dict) else {}
    cfg = _apply_env_overrides(cfg)

    # validate with pydantic if available
    if ConfigModel is not None:
        try:
            model = ConfigModel.parse_obj(cfg)
            _CACHED_MODEL = model
        except Exception:
            _CACHED_MODEL = None
    else:
        _CACHED_MODEL = None

    _CACHED_CONFIG = cfg
    return cfg


def get_config_model() -> Optional[object]:
    """Return a validated configuration model (if pydantic is available and validation passed)."""
    global _CACHED_MODEL
    return _CACHED_MODEL


def clear_config_cache() -> None:
    """Clear cached config and model to force reload on next `load_config()`."""
    global _CACHED_CONFIG, _CACHED_MODEL
    _CACHED_CONFIG = None
    _CACHED_MODEL = None
