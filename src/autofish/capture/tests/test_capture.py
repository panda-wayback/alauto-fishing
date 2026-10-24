import threading
import time

import numpy as np
import pytest

import mss

from autofish.capture import (
    CaptureWorker,
    ScreenGrab,
    grab_primary,
    grab_roi,
    load_screen,
    roi_frame_size,
    save_screen,
    warmup,
)
from autofish.events.bus import AutofishBus
from autofish.events.topics import FrameEvent, RoiEvent, Topic
from autofish.locate.roi import Roi

SCALE = 2
MONITOR = {"left": 10, "top": 20, "width": 100, "height": 80}
BGRA = (10, 20, 30, 255)


class FakeShot:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def __array__(self, dtype=None, copy=None):
        arr = np.empty((self.height, self.width, 4), dtype=np.uint8)
        arr[...] = BGRA
        return arr if dtype is None else arr.astype(dtype)


@pytest.fixture
def fake_mss(monkeypatch):
    calls = []
    fail = {"on": False}

    class FakeMss:
        monitors = [dict(MONITOR), dict(MONITOR)]

        def grab(self, mon):
            calls.append(dict(mon))
            if fail["on"]:
                raise RuntimeError("grab failed")
            return FakeShot(int(mon["width"]) * SCALE, int(mon["height"]) * SCALE)

    monkeypatch.setattr(mss, "mss", FakeMss)
    return calls, fail


def in_thread(fn, *args):
    """新线程里调用，确保拿到打过补丁的 mss 实例。"""
    out = {}

    def run():
        try:
            out["v"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001
            out["e"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(5)
    if "e" in out:
        raise out["e"]
    return out["v"]


def wait_until(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_grab_roi_returns_rgb_physical_pixels(fake_mss):
    calls, _ = fake_mss
    roi = Roi(left=5, top=6, width=40, height=30)
    frame = in_thread(grab_roi, roi)
    assert frame.dtype == np.uint8
    assert frame.shape == (30 * SCALE, 40 * SCALE, 3)
    assert tuple(frame[0, 0]) == (BGRA[2], BGRA[1], BGRA[0])
    assert frame.flags["C_CONTIGUOUS"]
    assert calls[-1] == {"left": 5, "top": 6, "width": 40, "height": 30}


def test_grab_primary_returns_logical_points_with_origin_and_scale(fake_mss):
    grab = in_thread(grab_primary)
    assert isinstance(grab, ScreenGrab)
    assert (grab.origin_left, grab.origin_top) == (MONITOR["left"], MONITOR["top"])
    assert grab.scale > 0
    expected_h = max(1, round(MONITOR["height"] * SCALE / grab.scale))
    expected_w = max(1, round(MONITOR["width"] * SCALE / grab.scale))
    assert grab.rgb.shape == (expected_h, expected_w, 3)
    assert grab.rgb.dtype == np.uint8


def test_roi_frame_size_matches_primary_scale(fake_mss):
    roi = Roi(left=0, top=0, width=33, height=17)
    scale = in_thread(grab_primary).scale
    assert in_thread(roi_frame_size, roi) == (
        max(1, round(33 * scale)),
        max(1, round(17 * scale)),
    )


def test_warmup_grabs_small_region_without_error(fake_mss):
    calls, _ = fake_mss
    in_thread(warmup)
    assert calls and calls[-1]["width"] == 8 and calls[-1]["height"] == 8


def test_save_and_load_screen_roundtrip(tmp_path):
    rgb = np.zeros((12, 16, 3), dtype=np.uint8)
    rgb[..., 0] = 200
    rgb[3, 4] = (1, 2, 3)
    path = tmp_path / "sub" / "screen.png"
    out = save_screen(ScreenGrab(rgb=rgb, origin_left=-7, origin_top=9, scale=1.5), path)
    assert out == path and path.exists()
    assert path.with_suffix(".meta.json").exists()
    loaded = load_screen(path)
    assert np.array_equal(loaded.rgb, rgb)
    assert (loaded.origin_left, loaded.origin_top, loaded.scale) == (-7, 9, 1.5)


def test_load_screen_without_meta_defaults(tmp_path):
    from PIL import Image

    path = tmp_path / "plain.png"
    Image.fromarray(np.full((5, 6, 3), 7, dtype=np.uint8)).save(path)
    loaded = load_screen(path)
    assert loaded.rgb.shape == (5, 6, 3)
    assert (loaded.origin_left, loaded.origin_top, loaded.scale) == (0, 0, 1.0)


def test_worker_publishes_frames_for_current_roi(fake_mss):
    bus = AutofishBus()
    frames: list[FrameEvent] = []
    bus.subscribe(Topic.FRAME, frames.append)
    roi = Roi(left=0, top=0, width=20, height=10)
    bus.publish_roi(RoiEvent(roi=roi, version=1, ts=time.time(), source="manual"))
    worker = CaptureWorker(bus, fps=100)
    worker.start()
    try:
        assert worker.is_running()
        assert wait_until(lambda: len(frames) >= 3)
    finally:
        worker.stop()
    assert not worker.is_running()
    got = list(frames)
    for ev in got:
        assert ev.roi_version == 1
        assert ev.frame.shape == (10 * SCALE, 20 * SCALE, 3)
    seqs = [ev.seq for ev in got]
    assert seqs[0] == 1 and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_worker_without_roi_does_not_grab(fake_mss):
    calls, _ = fake_mss
    bus = AutofishBus()
    frames = []
    bus.subscribe(Topic.FRAME, frames.append)
    worker = CaptureWorker(bus, fps=100)
    worker.start()
    try:
        time.sleep(0.15)
    finally:
        worker.stop()
    assert frames == [] and calls == []


def test_worker_follows_roi_change_and_clear(fake_mss):
    bus = AutofishBus()
    frames: list[FrameEvent] = []
    bus.subscribe(Topic.FRAME, frames.append)
    bus.publish_roi(
        RoiEvent(roi=Roi(0, 0, 20, 10), version=1, ts=time.time(), source="manual")
    )
    worker = CaptureWorker(bus, fps=100)
    worker.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        bus.publish_roi(
            RoiEvent(roi=Roi(0, 0, 8, 6), version=2, ts=time.time(), source="manual")
        )
        assert wait_until(lambda: frames[-1].roi_version == 2)
        assert frames[-1].frame.shape == (6 * SCALE, 8 * SCALE, 3)
        bus.clear_roi()
        time.sleep(0.05)
        n = len(frames)
        time.sleep(0.1)
        assert len(frames) == n
    finally:
        worker.stop()


def test_worker_survives_grab_failure(fake_mss):
    calls, fail = fake_mss
    fail["on"] = True
    bus = AutofishBus()
    frames = []
    bus.subscribe(Topic.FRAME, frames.append)
    bus.publish_roi(
        RoiEvent(roi=Roi(0, 0, 20, 10), version=1, ts=time.time(), source="manual")
    )
    worker = CaptureWorker(bus, fps=100)
    worker.start()
    try:
        assert wait_until(lambda: len(calls) >= 2)
        assert frames == [] and worker.is_running()
        fail["on"] = False
        assert wait_until(lambda: len(frames) >= 1)
    finally:
        worker.stop()
