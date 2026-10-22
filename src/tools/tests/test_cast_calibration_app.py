import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from autofish.cast_calibration import CastCircle, load_cast_circle
from tools.cast_calibration_app import (
    CANVAS_W,
    DEFAULT_ANGLE,
    CastCalibrationWindow,
    CastCanvas,
)

SCREEN_SIZE = (1920, 1080)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    families = set(QFontDatabase.families())
    for fam in ("Helvetica", "Arial", "DejaVu Sans"):
        if fam in families:
            app.setFont(QFont(fam))
            break
    yield app


def sample_circle() -> CastCircle:
    return CastCircle(0.42, 0.62, 30, 0.35)


def test_canvas_draws_perspective_rings_and_drags_anchor(app):
    circle = sample_circle()
    changes = []
    canvas = CastCanvas(CANVAS_W, 405, circle, changes.append)
    canvas.repaint()

    canvas._move_center(QPoint(360, 243))  # 幕布中心的一半比例
    assert canvas.circle.cx == pytest.approx(0.5)
    assert canvas.circle.cy == pytest.approx(0.6)
    assert changes[-1] == canvas.circle


def test_window_starts_with_default_values(app, tmp_path):
    win = CastCalibrationWindow(tmp_path / "c.json", screen_size=SCREEN_SIZE)
    assert win.circle.angle_deg == DEFAULT_ANGLE
    assert win.circle.cx == pytest.approx(0.5)
    assert win.circle.cy == pytest.approx(0.62)
    assert win.circle.radius_ratio > 0


def test_angle_and_size_sliders_update_ratio(app, tmp_path):
    win = CastCalibrationWindow(tmp_path / "c.json", screen_size=SCREEN_SIZE)
    win.slider_angle.setValue(45)
    assert win.circle.angle_deg == 45
    assert win.canvas.circle.angle_deg == 45
    assert win.lbl_angle.text() == "45°"

    win.slider_size.setValue(50)
    assert win.circle.radius_ratio == pytest.approx(0.5)
    assert win.canvas.circle.radius_ratio == pytest.approx(0.5)


def test_save_writes_resolution_independent_ratios(app, tmp_path):
    path = tmp_path / "c.json"
    win = CastCalibrationWindow(path, screen_size=SCREEN_SIZE)
    win.circle = CastCircle(0.5, 0.5, 35, 0.4)
    win._save()

    saved = load_cast_circle(path)
    assert saved == CastCircle(0.5, 0.5, 35, 0.4)
    # 同一份数据在更大屏幕上等比放大
    assert saved.radius_for(1920, 1080) == pytest.approx(432)
    assert saved.radius_for(2560, 1440) == pytest.approx(576)
    assert win.saved_circle == saved


def test_existing_calibration_loads(app, tmp_path):
    from autofish.cast_calibration import save_cast_circle

    path = tmp_path / "c.json"
    save_cast_circle(CastCircle(0.5, 0.5, 42, 0.3), path)
    win = CastCalibrationWindow(path, screen_size=SCREEN_SIZE)
    assert win.circle == CastCircle(0.5, 0.5, 42, 0.3)
    assert win.slider_angle.value() == 42
    assert win.slider_size.value() == 30
