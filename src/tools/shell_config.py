"""调试壳可持久化设置（data/shell_settings.json）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from common.paths import data_root

_SETTINGS_NAME = "shell_settings.json"


@dataclass
class ShellSettings:
    sound_threshold: float = 0.70
    press_lo: float = 70.6
    press_hi: float = 74.4
    release_lo: float = 76.6
    release_hi: float = 79.2
    press_interval_s: float = 0.0
    stay_on_top: bool = True


def settings_path() -> Path:
    return data_root() / _SETTINGS_NAME


def load_shell_settings() -> ShellSettings:
    path = settings_path()
    if not path.is_file():
        return ShellSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ShellSettings()
    base = ShellSettings()
    out = ShellSettings()
    for k in asdict(base):
        if k in data:
            setattr(out, k, data[k])
    out.sound_threshold = float(max(0.15, min(0.80, out.sound_threshold)))
    out.press_interval_s = float(max(0.0, min(0.3, out.press_interval_s)))
    return out


def save_shell_settings(settings: ShellSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
