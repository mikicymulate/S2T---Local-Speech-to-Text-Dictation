"""Configuration: config.json in the project directory, created with defaults on first run.

The TypedDicts below describe the exact shape of that file. They are the single source of
truth for the config schema — every other module takes these types rather than a bare dict,
so a typo like cfg["whipser"] or a wrong value type is caught statically.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypeAlias, TypedDict, cast

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
HISTORY_PATH = APP_DIR / "history.jsonl"
LOG_PATH = APP_DIR / "s2t.log"

# A sounddevice input device: an index, a name substring, or None for the system default.
MicDevice: TypeAlias = int | str | None
# How the transcript reaches the focused app (see injector.py).
InsertMode = Literal["paste", "type", "clipboard_only"]


class WhisperConfig(TypedDict):
    model: str
    device: str
    compute_type: str
    language: str | None  # None = auto-detect


class HotkeyConfig(TypedDict):
    hold: str
    toggle: str


class LMStudioConfig(TypedDict):
    enabled: bool
    base_url: str
    model: str
    gpu_offload: str  # "off", "max", or "0".."1"
    timeout_seconds: int
    auto_start_server: bool


class Config(TypedDict):
    mic_device: MicDevice
    whisper: WhisperConfig
    hotkeys: HotkeyConfig
    insert_mode: InsertMode
    restore_clipboard: bool
    lmstudio: LMStudioConfig
    dictionary: dict[str, str]
    sound_cues: bool
    max_record_seconds: int


DEFAULTS: Config = {
    # sounddevice input device index or name substring; null = system default mic
    "mic_device": None,
    "whisper": {
        # tiny / base / small / medium / large-v3 / distil-large-v3 / large-v3-turbo
        "model": "small",
        "device": "cpu",
        "compute_type": "int8",
        # null = auto-detect; or a language code like "en"
        "language": None,
    },
    "hotkeys": {
        # hold to talk, release to insert
        "hold": "right ctrl",
        # press once to start hands-free recording, again to stop
        "toggle": "f8",
    },
    # paste = Ctrl+V into the focused app | type = simulate keystrokes | clipboard_only
    "insert_mode": "paste",
    # true: put whatever was on the clipboard before dictation back afterwards
    # false (default): leave the transcript on the clipboard so you can paste it again
    "restore_clipboard": False,
    "lmstudio": {
        "enabled": True,
        # 127.0.0.1, NOT localhost: LM Studio listens on IPv4 only and localhost
        # resolves to ::1 first, which can black-hole for minutes on some machines
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "google/gemma-4-e4b",
        # `lms load --gpu` value: "off", "max", or 0..1. "off" avoids thrashing when
        # the model doesn't fit in VRAM (models larger than ~4 GB on this machine)
        "gpu_offload": "off",
        "timeout_seconds": 15,
        # try `lms server start` if the server is unreachable at startup
        "auto_start_server": True,
    },
    # vocabulary corrections applied by the LLM: {"what whisper hears": "what you meant"}
    "dictionary": {},
    "sound_cues": True,
    "max_record_seconds": 300,
}


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        log.info("Created default config at %s", CONFIG_PATH)
        return copy.deepcopy(DEFAULTS)
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not read %s (%s); using defaults", CONFIG_PATH, exc)
        return copy.deepcopy(DEFAULTS)
    # user config is untrusted JSON; _merge layers it over DEFAULTS so every key is present
    return cast(Config, _merge(DEFAULTS, user))


def save_config(cfg: Config) -> bool:
    """Persist the config dict back to config.json. Returns True on success."""
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except OSError:
        log.exception("Could not write %s", CONFIG_PATH)
        return False
