import json
from functools import lru_cache

import cv2
import numpy as np
import pytest

from autofish.events.topics import BobberHit as EventsBobberHit
from autofish.detect import (
    BobberAnchorDetector,
    BobberHit,
    FindBobber,
    apply_manual_bar,
    detect,
    get_detector,
)
from autofish.detect.bobber import green_zone_mask, pixel_to_pos
from common.paths import bundle_root

TEST_DIR = bundle_root() / "data" / "test"
BASELINE = json.loads((TEST_DIR / "find_bobber_baseline.json").read_text(encoding="utf-8"))
CENTER_TOL = float(BASELINE["tolerance"]["center_px"])
HIT_CASES = [c for c in BASELINE["cases"] if c["status"] == "HIT"]
SAMPLE = next(c for c in HIT_CASES if c["file"].startswith("a956139864609deb"))


@lru_cache(maxsize=None)
def load_rgb(name: str) -> np.ndarray:
    bgr = cv2.imread(str(TEST_DIR / name))
    assert bgr is not None, name
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb.setflags(write=False)
    return rgb


def blank_images() -> list[np.ndarray]:
    rng = np.random.default_rng(0)
    return [
        np.zeros((600, 800, 3), np.uint8),
        np.full((600, 800, 3), 255, np.uint8),
        np.full((600, 800, 3), (60, 160, 60), np.uint8),
        np.full((600, 800, 3), (240, 120, 30), np.uint8),
        rng.integers(0, 256, (600, 800, 3), dtype=np.uint8),
    ]


def reset_global() -> None:
    apply_manual_bar(None)
    get_detector().clear_bar_lock()


@pytest.fixture
def global_detector():
    reset_global()
    yield get_detector()
    reset_global()


def assert_full_hit(hit: BobberHit | None) -> BobberHit:
    assert hit is not None
    assert hit.bar_width > 0 and hit.bar_height > 0
    assert hit.bar_left < hit.x < hit.bar_left + hit.bar_width
    assert 0.0 <= hit.pos <= 100.0
    expect = 100.0 * (hit.x - hit.bar_left) / hit.bar_width
    assert hit.pos == pytest.approx(expect, abs=1.0)
    return hit


def assert_near(hit, x: float, y: float, tol: float = CENTER_TOL) -> None:
    assert abs(hit.x - x) <= tol and abs(hit.y - y) <= tol, (hit.x, hit.y, x, y)


@pytest.mark.parametrize("case", HIT_CASES, ids=lambda c: c["file"])
def test_detect_matches_baseline(global_detector, case):
    hit = assert_full_hit(detect(load_rgb(case["file"])))
    assert_near(hit, case["x"], case["y"])
    assert hit.detect_ms >= 0.0


def test_blank_and_bad_inputs_return_none(global_detector):
    for img in blank_images():
        assert detect(img) is None
    assert detect(np.zeros((600, 800), np.uint8)) is None
    assert detect(np.zeros((10, 10, 3), np.uint8)) is None
    assert global_detector.program_bar is None


def test_large_input_maps_back_to_original_coords():
    rgb = load_rgb(SAMPLE["file"])
    big = cv2.resize(rgb, (rgb.shape[1] * 2, rgb.shape[0] * 2))
    small_hit = assert_full_hit(BobberAnchorDetector().detect(rgb))
    big_hit = assert_full_hit(BobberAnchorDetector().detect(big))
    assert_near(big_hit, SAMPLE["x"] * 2, SAMPLE["y"] * 2, tol=CENTER_TOL * 2)
    assert big_hit.bar_left == pytest.approx(small_hit.bar_left * 2, abs=12)
    assert big_hit.bar_width == pytest.approx(small_hit.bar_width * 2, abs=24)
    assert big_hit.pos == pytest.approx(small_hit.pos, abs=3.0)
    assert big_hit.pixel_count == pytest.approx(small_hit.pixel_count * 4, rel=0.3)


def test_bobber_only_hit_when_bar_ends_missing():
    x0, y0 = 380, 300
    crop = np.ascontiguousarray(load_rgb(SAMPLE["file"])[y0:600, x0:620])
    det = BobberAnchorDetector()
    hit = det.detect(crop)
    assert hit is not None
    assert (hit.bar_left, hit.bar_top, hit.bar_width, hit.bar_height) == (0, 0, 0, 0)
    assert_near(hit, SAMPLE["x"] - x0, SAMPLE["y"] - y0)
    assert det.program_bar is None
    assert det.bar_locked is False


def test_program_lock_set_after_full_hit_and_cleared():
    det = BobberAnchorDetector()
    assert det.program_bar is None and det.bar_locked is False
    hit = assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    bar = det.program_bar
    assert bar is not None and det.bar_locked is True
    assert bar == pytest.approx(
        (hit.bar_left, hit.bar_top, hit.bar_width, hit.bar_height), abs=1.0
    )
    det.clear_bar_lock()
    assert det.program_bar is None and det.bar_locked is False


def test_seed_program_bar_locks_without_follow():
    det = BobberAnchorDetector()
    hit = assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    box = (
        float(hit.bar_left),
        float(hit.bar_top),
        float(hit.bar_width),
        float(hit.bar_height),
    )
    det.clear_bar_lock()
    det.seed_program_bar(box)
    assert det.program_bar == pytest.approx(box)
    assert det.bar_locked is True
    assert det._follow_xy is None
    hit2 = assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    assert hit2.pos == pytest.approx(hit.pos, abs=3.0)
    det.seed_program_bar(None)
    assert det.program_bar is None and det.bar_locked is False


def test_program_lock_survives_miss():
    det = BobberAnchorDetector()
    assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    bar = det.program_bar
    for _ in range(3):
        assert det.detect(np.zeros((698, 800, 3), np.uint8)) is None
    assert det.program_bar == bar and det.bar_locked is True


def test_program_lock_clears_after_sustained_miss():
    from autofish.detect.bobber_anchor import _BAR_LOCK_AUTO_CLEAR_FRAMES

    det = BobberAnchorDetector()
    assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    assert det.bar_locked is True
    blank = np.zeros((698, 800, 3), np.uint8)
    for _ in range(_BAR_LOCK_AUTO_CLEAR_FRAMES):
        det.detect(blank)
    assert det.program_bar is None and det.bar_locked is False
    hit = assert_full_hit(det.detect(load_rgb(SAMPLE["file"])))
    assert hit.bar_width > 0


def test_apply_manual_bar_overrides_bar_and_pos(global_detector):
    rgb = load_rgb(SAMPLE["file"])
    auto = assert_full_hit(detect(rgb))
    box = (auto.bar_left - 40.0, auto.bar_top, auto.bar_width, auto.bar_height)
    apply_manual_bar(box)
    assert global_detector.manual_bar == box
    assert global_detector.bar_locked is True
    hit = assert_full_hit(detect(rgb))
    assert (hit.bar_left, hit.bar_top, hit.bar_width, hit.bar_height) == pytest.approx(box)
    assert_near(hit, SAMPLE["x"], SAMPLE["y"])
    assert hit.pos == pytest.approx(pixel_to_pos(hit.x - box[0], int(box[2])), abs=0.5)
    assert hit.pos > auto.pos + 5.0


def test_manual_bar_far_from_bobber_gives_no_reading(global_detector):
    apply_manual_bar((10.0, 10.0, 200.0, 30.0))
    rgb = load_rgb(SAMPLE["file"])
    for _ in range(3):
        assert detect(rgb) is None
    assert global_detector.program_bar is None


def test_clear_manual_bar_restores_auto_bar(global_detector):
    rgb = load_rgb(SAMPLE["file"])
    apply_manual_bar((10.0, 10.0, 200.0, 30.0))
    detect(rgb)
    apply_manual_bar(None)
    assert global_detector.manual_bar is None
    hit = assert_full_hit(detect(rgb))
    assert hit.bar_left != pytest.approx(10.0)
    assert_near(hit, SAMPLE["x"], SAMPLE["y"])


def test_get_detector_singleton_and_bobber_hit_reexport():
    det = get_detector()
    assert det is get_detector()
    assert det.name == "bobber_anchor"
    assert callable(det.detect)
    assert BobberHit is EventsBobberHit


def test_missing_assets_raise(tmp_path):
    missing = tmp_path / "nope.png"
    with pytest.raises(FileNotFoundError):
        FindBobber(missing)
    with pytest.raises(FileNotFoundError):
        BobberAnchorDetector(endcap_left_path=missing)
    with pytest.raises(FileNotFoundError):
        BobberAnchorDetector(bobber_path=missing)


def test_pixel_to_pos():
    assert pixel_to_pos(0, 101) == 0.0
    assert pixel_to_pos(50, 101) == pytest.approx(50.0)
    assert pixel_to_pos(100, 101) == pytest.approx(100.0)
    assert pixel_to_pos(-5, 101) == 0.0
    assert pixel_to_pos(500, 101) == 100.0
    assert pixel_to_pos(3, 1) == 0.0
    assert pixel_to_pos(3, 0) == 0.0


def test_green_zone_mask():
    img = np.zeros((4, 6, 3), np.uint8)
    img[:, :2] = (60, 160, 60)
    img[:, 2:4] = (220, 40, 40)
    mask = green_zone_mask(img)
    assert mask.shape == (4, 6) and mask.dtype == np.uint8
    assert set(np.unique(mask)) <= {0, 255}
    assert (mask[:, :2] == 255).all()
    assert (mask[:, 2:] == 0).all()
    with pytest.raises(ValueError):
        green_zone_mask(np.zeros((4, 6), np.uint8))
