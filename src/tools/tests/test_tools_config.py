import json
import os
import sys
from dataclasses import asdict

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools import shell_config, shell_theme
from tools.shell_config import (
    ShellSettings,
    bundled_settings_path,
    load_default_shell_settings,
    load_shell_settings,
    save_bundled_shell_settings,
    save_shell_settings,
    settings_path,
)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    assets = tmp_path / "assets"
    monkeypatch.setattr(shell_config, "data_root", lambda: data)
    monkeypatch.setattr(shell_config, "assets_dir", lambda: assets)
    return data, assets


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")


def test_defaults_without_files(dirs):
    s = load_shell_settings()
    assert s == ShellSettings()
    assert s.sound_enabled is False
    assert s.auto_bobber_enabled is True
    assert s.sound_threshold == pytest.approx(0.70)
    assert (s.press_lo, s.press_hi, s.release_lo, s.release_hi) == (70.6, 74.4, 76.6, 79.2)
    assert s.compact_mode is False
    assert (s.click_delay_lo_s, s.click_delay_hi_s) == (0.3, 1.5)
    assert (s.click_hold_lo_s, s.click_hold_hi_s) == (0.7, 1.5)
    assert (s.click_after_lo_s, s.click_after_hi_s) == (0.2, 0.8)
    assert s.cast_count == 5
    assert s.cast_start_hotkey == "F8"
    assert s.cast_stop_hotkey == "F9"
    assert (s.cast_wait_lo_s, s.cast_wait_hi_s) == (3.0, 3.0)
    assert s.cast_full_charge_s == pytest.approx(1.0)
    assert s.auto_cast_enabled is False


def test_bundled_used_when_no_user_file(dirs):
    data, assets = dirs
    _write(assets / "shell_settings.json", {"sound_threshold": 0.8, "sound_enabled": True})
    assert bundled_settings_path() == assets / "shell_settings.json"
    s = load_shell_settings()
    assert s.sound_threshold == pytest.approx(0.8)
    assert s.sound_enabled is True


def test_user_overrides_bundled_and_merges_defaults(dirs):
    data, assets = dirs
    _write(assets / "shell_settings.json", {"sound_threshold": 0.8, "press_lo": 60.0})
    _write(data / "shell_settings.json", {"press_hi": 75.0, "bogus_key": 1})
    assert settings_path() == data / "shell_settings.json"
    s = load_shell_settings()
    assert s.press_hi == 75.0
    assert s.sound_threshold == pytest.approx(0.70)
    assert s.press_lo == 70.6
    assert not hasattr(s, "bogus_key")


@pytest.mark.parametrize("bad", ["{not json", "[1, 2, 3]"])
def test_bad_user_file_falls_back_to_bundled(dirs, bad):
    data, assets = dirs
    _write(assets / "shell_settings.json", {"sound_threshold": 0.9})
    _write(data / "shell_settings.json", bad)
    assert load_shell_settings().sound_threshold == pytest.approx(0.9)


def test_auto_cast_enabled_roundtrip(dirs):
    data, _ = dirs
    _write(
        data / "shell_settings.json",
        {"auto_cast_enabled": True, "cast_count": 9, "cast_start_hotkey": "f6"},
    )
    s = load_shell_settings()
    assert s.auto_cast_enabled is True
    assert s.cast_count == 9
    assert s.cast_start_hotkey == "F6"
    assert s.cast_stop_hotkey == "F9"


def test_out_of_range_values_are_normalized(dirs):
    data, _ = dirs
    _write(
        data / "shell_settings.json",
        {
            "sound_threshold": 5.0,
            "press_interval_s": -1.0,
            "click_delay_lo_s": 2.0,
            "click_delay_hi_s": 1.0,
            "click_hold_lo_s": 0.0,
            "click_hold_hi_s": 0.0,
            "click_after_lo_s": 9.0,
            "click_after_hi_s": 9.0,
            "compact_mode": 1,
            "hud_x": 12.7,
            "cast_count": 99,
            "cast_start_hotkey": "nope",
            "cast_wait_lo_s": 40.0,
            "cast_wait_hi_s": -1.0,
            "cast_full_charge_s": 0.01,
        },
    )
    s = load_shell_settings()
    assert s.sound_threshold == 1.0
    assert s.press_interval_s == 0.0
    assert (s.click_delay_lo_s, s.click_delay_hi_s) == (1.0, 2.0)
    assert s.click_hold_lo_s == pytest.approx(0.05)
    assert s.click_hold_hi_s - s.click_hold_lo_s >= 0.05 - 1e-9
    assert s.click_after_lo_s == 5.0 and s.click_after_hi_s == 5.0
    assert s.compact_mode is True
    assert s.hud_x == 12
    assert s.cast_count == 20
    assert s.cast_start_hotkey == "F8"
    assert (s.cast_wait_lo_s, s.cast_wait_hi_s) == (0.0, 30.0)
    assert s.cast_full_charge_s == pytest.approx(0.05)

    _write(data / "shell_settings.json", {"sound_threshold": 0.0, "press_interval_s": 1.0})
    s = load_shell_settings()
    assert s.sound_threshold == pytest.approx(0.15)
    assert s.press_interval_s == pytest.approx(0.3)


def test_save_writes_all_keys_and_roundtrips(dirs):
    data, _ = dirs
    s = ShellSettings(sound_threshold=0.55, compact_mode=True, audio_device_name="BlackHole 2ch")
    save_shell_settings(s)
    raw = json.loads((data / "shell_settings.json").read_text(encoding="utf-8"))
    assert set(raw) == set(asdict(ShellSettings()))
    assert raw["sound_threshold"] == pytest.approx(0.55)
    back = load_shell_settings()
    assert back == s


def test_load_default_ignores_user_file_and_strips_machine_fields(dirs):
    data, assets = dirs
    assert load_default_shell_settings() == ShellSettings()
    _write(
        assets / "shell_settings.json",
        {
            "sound_threshold": 0.81,
            "sound_enabled": True,
            "press_lo": 71.2,
            "compact_mode": True,
            "audio_device_name": "Speakers",
            "window_x": 12,
            "window_w": 500,
            "hud_y": 40,
        },
    )
    _write(data / "shell_settings.json", {"sound_threshold": 0.2, "press_lo": 50.0})
    s = load_default_shell_settings()
    assert s.sound_threshold == pytest.approx(0.81)
    assert s.sound_enabled is True
    assert s.press_lo == pytest.approx(71.2)
    assert s.press_hi == 74.4
    assert s.compact_mode is False
    assert s.audio_device_name == ""
    assert (s.window_x, s.window_w, s.hud_y) == (-1, 0, -1)
    assert load_shell_settings().sound_threshold == pytest.approx(0.2)


def test_save_bundled_strips_machine_fields(dirs):
    _, assets = dirs
    s = ShellSettings(
        sound_threshold=0.66,
        sound_enabled=True,
        press_lo=60.0,
        compact_mode=True,
        hud_x=100,
        hud_y=200,
        window_x=10,
        window_y=20,
        window_w=500,
        window_h=900,
        audio_device_name="Speakers",
    )
    path = save_bundled_shell_settings(s)
    assert path == assets / "shell_settings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == set(asdict(ShellSettings()))
    assert raw["compact_mode"] is False
    assert (raw["hud_x"], raw["hud_y"], raw["window_x"], raw["window_y"]) == (-1, -1, -1, -1)
    assert (raw["window_w"], raw["window_h"]) == (0, 0)
    assert raw["audio_device_name"] == ""
    assert raw["sound_threshold"] == pytest.approx(0.66)
    assert raw["sound_enabled"] is True
    assert raw["press_lo"] == 60.0


def test_save_bundled_refused_when_frozen(dirs, monkeypatch, tmp_path):
    _, assets = dirs
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert shell_config.is_frozen_app() is True
    with pytest.raises(RuntimeError):
        save_bundled_shell_settings(ShellSettings())
    assert not (assets / "shell_settings.json").exists()


def test_theme_qss_contains_palette_and_applies():
    from PySide6.QtWidgets import QApplication, QWidget

    qss = shell_theme.global_qss()
    assert isinstance(qss, str) and qss.strip()
    for color in (shell_theme.BG, shell_theme.TEXT, shell_theme.ACCENT):
        assert color in qss
    canvas = shell_theme.preview_canvas_qss()
    assert shell_theme.PREVIEW_BG in canvas

    app = QApplication.instance() or QApplication([])
    w = QWidget()
    w.setStyleSheet(qss)
    w.setStyleSheet(canvas)
    assert w.styleSheet() == canvas
    w.deleteLater()
    app.processEvents()
