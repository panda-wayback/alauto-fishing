"""调试壳设置：用户 data/shell_settings.json + 打包默认 assets/shell_settings.json。"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from common.paths import assets_dir, data_root

_SETTINGS_NAME = "shell_settings.json"


def _clamp_pair(
    lo: float,
    hi: float,
    *,
    min_v: float,
    max_v: float,
    min_span: float = 0.0,
) -> tuple[float, float]:
    a = float(max(min_v, min(max_v, lo)))
    b = float(max(min_v, min(max_v, hi)))
    if b < a:
        a, b = b, a
    if b - a < min_span:
        b = min(max_v, a + min_span)
    return a, b


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
    # 开钓第一下：等待 / 长按（秒）
    click_delay_lo_s: float = 0.3
    click_delay_hi_s: float = 1.5
    click_hold_lo_s: float = 0.7
    click_hold_hi_s: float = 1.5
    click_after_lo_s: float = 0.2
    click_after_hi_s: float = 0.8


def settings_path() -> Path:
    """用户可写配置。"""
    return data_root() / _SETTINGS_NAME


def bundled_settings_path() -> Path:
    """随包默认配置（assets，冻结只读）。"""
    return assets_dir() / _SETTINGS_NAME


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


def _parse_settings_file(path: Path) -> ShellSettings | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    base = ShellSettings()
    out = ShellSettings()
    for k in asdict(base):
        if k in data:
            setattr(out, k, data[k])
    return _normalize_settings(out)


def _normalize_settings(out: ShellSettings) -> ShellSettings:
    out.sound_threshold = float(max(0.15, min(1.0, out.sound_threshold)))
    out.press_interval_s = float(max(0.0, min(0.3, out.press_interval_s)))
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
    out.click_delay_lo_s, out.click_delay_hi_s = _clamp_pair(
        float(out.click_delay_lo_s),
        float(out.click_delay_hi_s),
        min_v=0.0,
        max_v=5.0,
        min_span=0.05,
    )
    out.click_hold_lo_s, out.click_hold_hi_s = _clamp_pair(
        float(out.click_hold_lo_s),
        float(out.click_hold_hi_s),
        min_v=0.05,
        max_v=5.0,
        min_span=0.05,
    )
    out.click_after_lo_s, out.click_after_hi_s = _clamp_pair(
        float(out.click_after_lo_s),
        float(out.click_after_hi_s),
        min_v=0.0,
        max_v=5.0,
        min_span=0.05,
    )
    return out


def package_defaults_from(settings: ShellSettings) -> ShellSettings:
    """去掉机器相关字段，供写入 assets 打包默认。"""
    return _normalize_settings(
        replace(
            settings,
            compact_mode=False,
            hud_x=-1,
            hud_y=-1,
            window_x=-1,
            window_y=-1,
            window_w=0,
            window_h=0,
            audio_device_name="",
        )
    )


def load_shell_settings() -> ShellSettings:
    """用户文件优先；否则打包默认；再否则代码内建。"""
    user = _parse_settings_file(settings_path())
    if user is not None:
        return user
    bundled = _parse_settings_file(bundled_settings_path())
    if bundled is not None:
        return bundled
    return ShellSettings()


def save_shell_settings(settings: ShellSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(_normalize_settings(settings)), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def save_bundled_shell_settings(settings: ShellSettings) -> Path:
    """
    写入 assets/shell_settings.json（打包默认）。
    仅源码树可写；冻结包会抛错。
    """
    if is_frozen_app():
        raise RuntimeError("打包后的应用无法改内置默认，请在源码里「写入打包默认」后再打包")
    path = bundled_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = package_defaults_from(settings)
    path.write_text(
        json.dumps(asdict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
