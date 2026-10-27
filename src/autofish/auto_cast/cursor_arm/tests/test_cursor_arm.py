"""cursor_arm 黑盒：光标位图认漂 + grab mock + Watcher。"""

from __future__ import annotations

import time

import numpy as np
import pytest

from autofish.auto_cast.cursor_arm import (
    CursorArmWatcher,
    grab_around_cursor,
    grab_system_cursor,
    see_surface_bobber,
)


def _blob(h: int, w: int, cy: int, cx: int, r: int) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r


def _bobber_rgba() -> np.ndarray:
    img = np.zeros((80, 80, 4), dtype=np.uint8)
    # 蓝底半透明不算漂
    img[..., 2] = 160
    img[..., 3] = 0
    m = _blob(80, 80, 55, 40, 14)
    img[m] = (230, 220, 200, 255)
    m = _blob(80, 80, 42, 40, 8)
    img[m] = (200, 40, 40, 255)
    m = _blob(80, 80, 28, 40, 10)
    img[m] = (240, 180, 40, 255)
    return img


def test_see_surface_bobber_yellow_red_white():
    assert see_surface_bobber(_bobber_rgba()) is True


def _golden_icon_wrong_order_rgba() -> np.ndarray:
    """同样凑够黄/红/白三色占比，但纵向顺序与漂形相反（模拟系统光标主题图标误判）。"""
    img = np.zeros((80, 80, 4), dtype=np.uint8)
    img[..., 2] = 160
    img[..., 3] = 0
    # 白肚在最上、红带居中、黄羽在最下：与真漂（黄→红→白）顺序相反
    m = _blob(80, 80, 25, 40, 14)
    img[m] = (230, 220, 200, 255)
    m = _blob(80, 80, 42, 40, 8)
    img[m] = (200, 40, 40, 255)
    m = _blob(80, 80, 55, 40, 10)
    img[m] = (240, 180, 40, 255)
    return img


def test_see_surface_bobber_golden_icon_wrong_order_false():
    assert see_surface_bobber(_golden_icon_wrong_order_rgba()) is False


def test_see_surface_bobber_plain_blue_false():
    img = np.zeros((80, 80, 4), dtype=np.uint8)
    img[..., 0:3] = (40, 90, 160)
    img[..., 3] = 255
    assert see_surface_bobber(img) is False


def test_see_surface_bobber_empty_false():
    assert see_surface_bobber(np.zeros((2, 2, 4), dtype=np.uint8)) is False


def test_grab_system_cursor_mocked(monkeypatch):
    from autofish.auto_cast.cursor_arm import grab as grab_mod

    fake = np.zeros((32, 32, 4), dtype=np.uint8)
    fake[..., 3] = 255
    monkeypatch.setattr(grab_mod, "_grab_macos", lambda: fake)
    monkeypatch.setattr(grab_mod, "_grab_windows", lambda: None)
    out = grab_system_cursor()
    assert out is fake
    rgb = grab_around_cursor(100)
    assert rgb is not None and rgb.shape == (32, 32, 3)


def test_grab_system_cursor_none(monkeypatch):
    from autofish.auto_cast.cursor_arm import grab as grab_mod

    monkeypatch.setattr(grab_mod, "_grab_macos", lambda: None)
    monkeypatch.setattr(grab_mod, "_grab_windows", lambda: None)
    assert grab_system_cursor() is None


def test_watcher_armed_follows_detect(monkeypatch):
    from autofish.auto_cast.cursor_arm import watcher as wmod

    flips: list[bool] = []
    frames: list[tuple[np.ndarray, bool]] = []
    frame = _bobber_rgba()
    monkeypatch.setattr(wmod, "grab_system_cursor", lambda: frame)
    w = CursorArmWatcher(
        interval_s=0.05,
        on_armed_changed=flips.append,
        on_frame=lambda rgb, armed: frames.append((rgb, armed)),
    )
    w.start()
    try:
        assert w.armed is False
        w.set_enabled(True)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not w.armed:
            time.sleep(0.05)
        assert w.armed is True
        assert True in flips
        assert frames and frames[-1][1] is True
        assert w.last_frame is not None
        w.set_enabled(False)
        assert w.armed is False
        assert w.last_frame is None
        assert flips[-1] is False
    finally:
        w.stop()
    assert not w.is_running()
    assert w.armed is False
