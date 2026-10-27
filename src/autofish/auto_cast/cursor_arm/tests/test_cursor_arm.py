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


def _decorative_icon_low_coverage_rgba() -> np.ndarray:
    """顺序对、三色占比也各自达标，但整图大片是三色之外的不透明装饰色
    （模拟游戏里的篝火 / 可互动提示类图标：火焰顶 + 杯身，外围还有大片
    深色描边与水纹涟漪），合计三色占比明显偏低。
    """
    img = np.zeros((80, 80, 4), dtype=np.uint8)
    # 大片不透明深灰背景/涟漪装饰（非黄/红/肚三色），占满整图
    img[..., 0] = 60
    img[..., 1] = 65
    img[..., 2] = 75
    img[..., 3] = 255
    # 顺序正确的小块黄羽 / 红带 / 乳白肚，但面积相对整图很小
    m = _blob(80, 80, 55, 40, 6)
    img[m] = (230, 220, 200, 255)
    m = _blob(80, 80, 46, 40, 4)
    img[m] = (200, 40, 40, 255)
    m = _blob(80, 80, 32, 40, 9)
    img[m] = (240, 180, 40, 255)
    return img


def test_see_surface_bobber_low_color_coverage_false():
    img = _decorative_icon_low_coverage_rgba()
    # 三色各自占比与顺序都满足，只差「三色合计占比」这一道门槛
    assert see_surface_bobber(img) is False


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
