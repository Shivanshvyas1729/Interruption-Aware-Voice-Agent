import os
import yaml
from typing import Any

_VOICE_CONFIG: dict | None = None


def _resolve_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "config", "voice_settings.yaml")


def _load_yaml() -> dict:
    path = _resolve_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_voice_config() -> dict:
    global _VOICE_CONFIG
    if _VOICE_CONFIG is None:
        _VOICE_CONFIG = _load_yaml()
    return _VOICE_CONFIG


def reload_voice_config():
    global _VOICE_CONFIG
    _VOICE_CONFIG = _load_yaml()


def get(key_path: str, default: Any = None) -> Any:
    config = get_voice_config()
    parts = key_path.split(".")
    val = config
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
            if val is None:
                return default
        else:
            return default
    return val
