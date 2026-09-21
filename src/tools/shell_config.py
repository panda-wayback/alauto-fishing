"""调试壳可持久化设置（data/shell_settings.json）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
    compact_mode: bool = False
    hud_x: int = -1
    hud_y: int = -1
    # 主控勾选
    sound_enabled: bool = False
    auto_bobber_enabled: bool = True
    # 声音页：按名称匹配设备（索引会变）
    audio_device_name: str = ""
    # 完整态窗口几何（-1 / 0 表示未存）
    window_x: int = -1
    window_y: int = -1
    window_w: int = 0
    window_h: int = 0


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
    # 兼容旧键 hud_enabled
    if "compact_mode" not in data and "hud_enabled" in data:
        out.compact_mode = bool(data.get("hud_enabled"))
    out.compact_mode = bool(out.compact_mode)
    out.hud_x = int(out.hud_x)
    out.hud_y = int(out.hud_y)
    out.sound_enabled = bool(out.sound_enabled)
    out.auto_bobber_enabled = bool(out.auto_bobber_enabled)
    out.audio_device_name = str(out.audio_device_name or "")
    out.window_x = int(out.window_x)
    out.window_y = int(out.window_y)
    out.window_w = int(out.window_w)
    out.window_h = int(out.window_h)
    return out


def save_shell_settings(settings: ShellSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
