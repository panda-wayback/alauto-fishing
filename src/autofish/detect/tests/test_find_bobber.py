import importlib
import json
import os
import subprocess
import sys

import cv2
import numpy as np
import pytest

from autofish.detect import FindBobber
from common.paths import bundle_root

cli = importlib.import_module("autofish.detect.check_find_bobber_baseline")

ROOT = bundle_root()
TEST_DIR = ROOT / "data" / "test"
BASELINE = json.loads((TEST_DIR / "find_bobber_baseline.json").read_text(encoding="utf-8"))
TOL = BASELINE["tolerance"]
SAMPLE = next(c for c in BASELINE["cases"] if c["file"].startswith("a956139864609deb"))


def load_rgb(name: str) -> np.ndarray:
    return cv2.cvtColor(cv2.imread(str(TEST_DIR / name)), cv2.COLOR_BGR2RGB)


def assert_matches(loc, case, *, k: float = 1.0) -> None:
    assert loc is not None
    assert abs(loc.x - case["x"] * k) <= TOL["center_px"] * k
    assert abs(loc.y - case["y"] * k) <= TOL["center_px"] * k
    for key in ("left", "top", "width", "height"):
        assert abs(getattr(loc, key) - case[key] * k) <= TOL["box_px"] * k, key
    assert loc.score >= case["score"] + TOL["score_min_delta"]


@pytest.fixture(scope="module")
def sample_rgb():
    return load_rgb(SAMPLE["file"])


def test_blank_and_bad_inputs(sample_rgb):
    fb = FindBobber()
    rng = np.random.default_rng(1)
    for img in (
        np.zeros((600, 800, 3), np.uint8),
        np.full((600, 800, 3), 255, np.uint8),
        np.full((600, 800, 3), (240, 120, 30), np.uint8),
        rng.integers(0, 256, (600, 800, 3), dtype=np.uint8),
    ):
        assert fb.find(img) is None
    gray = np.zeros((600, 800), np.uint8)
    assert fb.find(gray) is None
    assert fb.find_candidates(gray) == []


def test_search_box_limits_search(sample_rgb):
    case = SAMPLE
    box = (case["left"] - 150, case["top"] - 20, case["width"] + 300, case["height"] + 30)
    loc = FindBobber().find(sample_rgb, search_box=box)
    assert_matches(loc, case)
    assert FindBobber().find(sample_rgb, search_box=(10, 10, 200, 100)) is None


def test_find_candidates_sorted_and_capped(sample_rgb):
    fb = FindBobber()
    cands = fb.find_candidates(sample_rgb, max_n=3)
    assert 1 <= len(cands) <= 3
    ranks = [c.rank for c in cands]
    assert ranks == sorted(ranks, reverse=True)
    assert_matches(cands[0], SAMPLE)
    assert len(fb.find_candidates(sample_rgb, max_n=1)) == 1


def test_lock_and_clear_scale_keep_result(sample_rgb):
    fb = FindBobber()
    first = fb.find(sample_rgb)
    assert_matches(first, SAMPLE)
    assert_matches(fb.find(sample_rgb), SAMPLE)
    fb.clear_locked_scale()
    assert_matches(fb.find(sample_rgb), SAMPLE)
    fb.lock_scale(None)
    fb.lock_scale(0)
    assert_matches(fb.find(sample_rgb), SAMPLE)


def test_large_input_maps_back(sample_rgb):
    big = cv2.resize(sample_rgb, (sample_rgb.shape[1] * 2, sample_rgb.shape[0] * 2))
    assert_matches(FindBobber().find(big), SAMPLE, k=2.0)


def test_cli_passes_on_repo_baseline():
    env = dict(os.environ)
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "autofish.detect.check_find_bobber_baseline"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[FAIL]" not in proc.stdout
    assert proc.stdout.count("[OK]") == len(BASELINE["cases"])


def _fake_root(tmp_path, monkeypatch, cases):
    test_dir = tmp_path / "data" / "test"
    test_dir.mkdir(parents=True)
    cv2.imwrite(str(test_dir / "blank.png"), np.zeros((300, 400, 3), np.uint8))
    if cases is not None:
        (test_dir / "find_bobber_baseline.json").write_text(
            json.dumps({"tolerance": TOL, "cases": cases}), encoding="utf-8"
        )
    monkeypatch.setattr(cli, "bundle_root", lambda: tmp_path)


def test_cli_missing_baseline_exits_2(tmp_path, monkeypatch):
    _fake_root(tmp_path, monkeypatch, None)
    assert cli.main() == 2


def test_cli_expected_hit_but_miss_exits_1(tmp_path, monkeypatch, capsys):
    case = {k: SAMPLE[k] for k in ("x", "y", "left", "top", "width", "height", "score")}
    _fake_root(tmp_path, monkeypatch, [dict(case, file="blank.png", status="HIT")])
    assert cli.main() == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_cli_expected_miss_exits_0(tmp_path, monkeypatch, capsys):
    _fake_root(tmp_path, monkeypatch, [{"file": "blank.png", "status": "MISS"}])
    assert cli.main() == 0
    assert "[OK]" in capsys.readouterr().out
