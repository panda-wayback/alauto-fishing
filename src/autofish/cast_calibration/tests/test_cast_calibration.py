import dataclasses
import json
import math

import pytest

import autofish.cast_calibration.circle as circle_mod
from autofish.cast_calibration import (
    CastCircle,
    load_cast_circle,
    save_bundled_cast_circle,
    save_cast_circle,
)


def test_validation_and_immutable():
    with pytest.raises(ValueError):
        CastCircle(0.5, 0.5, 0)
    with pytest.raises(ValueError):
        CastCircle(0.5, 0.5, 91)
    with pytest.raises(ValueError):
        CastCircle(0.5, 0.5, 30, radius_ratio=0)
    c = CastCircle(0.5, 0.5, 45)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.angle_deg = 30  # type: ignore[misc]


def test_ratio_scales_to_any_screen():
    c = CastCircle(0.5, 0.6, 30, radius_ratio=0.4)
    assert c.anchor(1000, 800) == (500, 480)
    assert c.radius_for(1000, 800) == pytest.approx(320)  # min(1000,800)*0.4
    assert c.anchor(2000, 1600) == (1000, 960)
    assert c.radius_for(2000, 1600) == pytest.approx(640)
    with pytest.raises(ValueError):
        c.anchor(0, 800)


def test_from_pixels():
    c = CastCircle.from_pixels(500, 480, 320, 1000, 800, 30)
    assert c.cx == 0.5
    assert c.cy == pytest.approx(0.6)
    assert c.radius_ratio == pytest.approx(0.4)
    assert c.angle_deg == 30
    with pytest.raises(ValueError):
        CastCircle.from_pixels(1, 1, 1, 0, 800, 30)


def test_top_view_90_degrees_is_true_circle():
    c = CastCircle(0.5, 0.5, 90, radius_ratio=0.5)
    w, h = 800, 600
    ax, ay = c.anchor(w, h)
    r = c.radius_for(w, h)
    assert c.perspective == pytest.approx(0.0)
    for phi_deg in (0, 90, 180, 270, 45):
        x, y = c.project(1.0, math.radians(phi_deg), w, h)
        assert math.hypot(x - ax, y - ay) == pytest.approx(r, abs=1e-6)
    assert c.normalized_radius(ax + r, ay, w, h) == pytest.approx(1.0)


def test_perspective_is_wider_near_bottom_and_compressed_at_top():
    w, h = 800, 600
    c = CastCircle(0.5, 0.5, 30, radius_ratio=0.5)
    _, top = c.project(1.0, math.radians(-90), w, h)
    _, bottom = c.project(1.0, math.radians(90), w, h)
    ax, ay = c.anchor(w, h)
    near = bottom - ay
    far = ay - top
    assert near > far  # 近大远小
    assert c.perspective > 0


def test_normalized_radius_inverts_projection():
    w, h = 800, 600
    c = CastCircle(0.5, 0.55, 30, radius_ratio=0.45)
    for rho in (0.0, 0.25, 0.5, 0.75, 1.0):
        for phi_deg in (0, 45, 90, 135, 200, 310):
            x, y = c.project(rho, math.radians(phi_deg), w, h)
            assert c.normalized_radius(x, y, w, h) == pytest.approx(rho, abs=1e-9)
    ax, ay = c.anchor(w, h)
    assert c.normalized_radius(ax, ay, w, h) == pytest.approx(0.0)
    x, y = c.project(1.3, math.radians(60), w, h)
    assert c.normalized_radius(x, y, w, h) > 1.0


def test_target_power_ratio_clamped():
    w, h = 800, 600
    c = CastCircle(0.5, 0.55, 30, radius_ratio=0.45)
    ax, ay = c.anchor(w, h)
    assert c.target_power_ratio(ax, ay, w, h) == pytest.approx(0.0)
    # 环上各方向都是 1
    for phi_deg in (0, 90, 180, 270, 315):
        x, y = c.project(1.0, math.radians(phi_deg), w, h)
        assert c.target_power_ratio(x, y, w, h) == pytest.approx(1.0, abs=1e-9)
    # 环内 0.5 不被夹
    x, y = c.project(0.5, math.radians(30), w, h)
    assert c.target_power_ratio(x, y, w, h) == pytest.approx(0.5, abs=1e-9)
    # 环外夹到 1
    x, y = c.project(1.3, math.radians(60), w, h)
    assert c.target_power_ratio(x, y, w, h) == 1.0
    assert 0.0 <= c.target_power_ratio(-100000, -100000, w, h) <= 1.0


def test_updaters():
    c = CastCircle(0.5, 0.6, 30, 0.35)
    assert c.with_angle(60) == CastCircle(0.5, 0.6, 60, 0.35)
    assert c.with_anchor_ratio(0.4, 0.3) == CastCircle(0.4, 0.3, 30, 0.35)
    assert c.with_radius_ratio(0.5) == CastCircle(0.5, 0.6, 30, 0.5)


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "nested" / "cast_circle.json"
    c = CastCircle(0.50026, 0.5743, 27.0, 0.35)
    assert save_cast_circle(c, path) == path
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"cx", "cy", "angle_deg", "radius_ratio"}
    assert load_cast_circle(path) == c


def test_load_old_file_without_radius_ratio(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps({"cx": 0.5, "cy": 0.6, "angle_deg": 30}),
        encoding="utf-8",
    )
    c = load_cast_circle(path)
    assert c.radius_ratio == circle_mod.DEFAULT_RADIUS_RATIO


@pytest.mark.parametrize(
    "payload",
    (
        "not json",
        "{}",
        '{"cx": 0.5, "cy": 0.6}',
        '{"cx": "x", "cy": 0.6, "angle_deg": 30, "radius_ratio": 0.35}',
        '{"cx": 0.5, "cy": 0.6, "angle_deg": 0, "radius_ratio": 0.35}',
        '{"cx": 0.5, "cy": 0.6, "angle_deg": 30, "radius_ratio": 0}',
    ),
)
def test_load_rejects_bad_files(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises((json.JSONDecodeError, KeyError, TypeError, ValueError)):
        load_cast_circle(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cast_circle(tmp_path / "missing.json")


def test_default_path_used_when_none(tmp_path, monkeypatch):
    fake_default = tmp_path / "data" / "cast_circle.json"
    fake_bundled = tmp_path / "assets" / "cast_circle.json"
    monkeypatch.setattr(circle_mod, "DEFAULT_CAST_CIRCLE_PATH", fake_default)
    monkeypatch.setattr(circle_mod, "BUNDLED_CAST_CIRCLE_PATH", fake_bundled)
    c = CastCircle(0.5, 0.6, 30)
    assert save_cast_circle(c) == fake_default
    assert load_cast_circle() == c


def test_load_falls_back_to_bundled(tmp_path, monkeypatch):
    fake_default = tmp_path / "data" / "cast_circle.json"
    fake_bundled = tmp_path / "assets" / "cast_circle.json"
    monkeypatch.setattr(circle_mod, "DEFAULT_CAST_CIRCLE_PATH", fake_default)
    monkeypatch.setattr(circle_mod, "BUNDLED_CAST_CIRCLE_PATH", fake_bundled)
    monkeypatch.setattr(circle_mod, "_is_frozen_app", lambda: False)
    c = CastCircle(0.4, 0.5, 40, 0.4)
    assert save_bundled_cast_circle(c) == fake_bundled
    assert not fake_default.exists()
    assert load_cast_circle() == c


def test_save_bundled_refuses_frozen(tmp_path, monkeypatch):
    fake_bundled = tmp_path / "assets" / "cast_circle.json"
    monkeypatch.setattr(circle_mod, "BUNDLED_CAST_CIRCLE_PATH", fake_bundled)
    monkeypatch.setattr(circle_mod, "_is_frozen_app", lambda: True)
    with pytest.raises(RuntimeError):
        save_bundled_cast_circle(CastCircle(0.5, 0.6, 30))
    assert not fake_bundled.exists()
