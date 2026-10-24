import threading
import time

import numpy as np
import pytest

from autofish.detect import BobberHit, DetectorWorker, get_detector
from autofish.events.bus import AutofishBus
from autofish.events.topics import FrameEvent, RoiEvent, Topic

FULL = BobberHit(pos=42.0, x=50.0, y=10.0, pixel_count=9, bar_left=8.0, bar_top=5.0, bar_width=100.0, bar_height=10.0)
ONLY = BobberHit(pos=0.0, x=50.0, y=10.0, pixel_count=9)


class FakeDetector:
    """替换单例识别器的 detect / clear_bar_lock，按 frame[0,0,0] 取结果。"""

    def __init__(self):
        self.results = {}
        self.errors = set()
        self.gate = None
        self.started = threading.Event()
        self.seen = []
        self.clears = 0

    def detect(self, rgb):
        tag = int(rgb[0, 0, 0])
        self.seen.append(tag)
        self.started.set()
        if self.gate is not None and tag == 1:
            self.gate.wait(5.0)
        if tag in self.errors:
            raise RuntimeError("boom")
        return self.results.get(tag)

    def clear_bar_lock(self):
        self.clears += 1


@pytest.fixture
def fake(monkeypatch):
    f = FakeDetector()
    det = get_detector()
    monkeypatch.setattr(det, "detect", f.detect)
    monkeypatch.setattr(det, "clear_bar_lock", f.clear_bar_lock)
    return f


@pytest.fixture
def rig(fake):
    bus = AutofishBus()
    got = []
    bus.subscribe(Topic.POS, got.append)
    worker = DetectorWorker(bus)
    worker.start()
    yield bus, worker, got
    worker.stop()


def frame(tag: int, seq: int, version: int = 0) -> FrameEvent:
    img = np.full((4, 4, 3), tag, np.uint8)
    return FrameEvent(frame=img, roi_version=version, ts=1000.0 + seq, seq=seq)


def wait_for(pred, timeout: float = 3.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("timeout")


def test_frame_produces_aligned_pos(fake, rig):
    bus, _worker, got = rig
    fake.results[1] = FULL
    ev = frame(1, seq=7)
    bus.publish_frame(ev)
    wait_for(lambda: len(got) == 1)
    pos = got[0]
    assert pos.pos == 42.0 and pos.hit is FULL
    assert pos.frame_seq == 7 and pos.roi_version == 0
    assert pos.frame_ts == ev.ts and pos.frame is ev.frame
    assert pos.detect_ms >= 0.0


def test_bobber_only_and_miss(fake, rig):
    bus, _worker, got = rig
    fake.results[1] = ONLY
    bus.publish_frame(frame(1, seq=1))
    wait_for(lambda: len(got) == 1)
    bus.publish_frame(frame(2, seq=2))
    wait_for(lambda: len(got) == 2)
    assert got[0].pos is None and got[0].hit is ONLY
    assert got[1].pos is None and got[1].hit is None


def test_backlog_keeps_only_latest(fake, rig):
    bus, _worker, got = rig
    fake.gate = threading.Event()
    fake.results = {1: FULL, 5: FULL}
    bus.publish_frame(frame(1, seq=1))
    assert fake.started.wait(3.0)
    for seq in (2, 3, 4, 5):
        bus.publish_frame(frame(seq, seq=seq))
    fake.gate.set()
    wait_for(lambda: len(got) == 2)
    time.sleep(0.2)
    assert [p.frame_seq for p in got] == [1, 5]
    assert fake.seen == [1, 5]


def test_old_seq_ignored_and_restart_resets(fake, rig):
    bus, worker, got = rig
    bus.publish_frame(frame(1, seq=5))
    wait_for(lambda: len(got) == 1)
    bus.publish_frame(frame(2, seq=3))
    bus.publish_frame(frame(2, seq=5))
    time.sleep(0.3)
    assert [p.frame_seq for p in got] == [5]
    worker.stop()
    bus.reset_pos_seq()
    worker.start()
    bus.publish_frame(frame(3, seq=1))
    wait_for(lambda: len(got) == 2)
    assert got[1].frame_seq == 1


def test_exception_does_not_kill_thread(fake, rig):
    bus, worker, got = rig
    fake.errors.add(1)
    fake.results[2] = FULL
    bus.publish_frame(frame(1, seq=1))
    wait_for(lambda: len(got) == 1)
    assert got[0].pos is None and got[0].hit is None and got[0].detect_ms == 0.0
    assert worker.is_running()
    bus.publish_frame(frame(2, seq=2))
    wait_for(lambda: len(got) == 2)
    assert got[1].pos == 42.0


def test_roi_version_change_clears_bar_lock(fake, rig):
    bus, _worker, got = rig
    bus.publish_frame(frame(1, seq=1))
    wait_for(lambda: len(got) == 1)
    assert fake.clears == 0
    bus.publish_roi(RoiEvent(roi=None, version=1, ts=0.0, source="clear"))
    bus.publish_frame(frame(2, seq=2, version=1))
    wait_for(lambda: len(got) == 2)
    assert fake.clears == 1
    assert got[1].roi_version == 1
    bus.publish_frame(frame(3, seq=3, version=1))
    wait_for(lambda: len(got) == 3)
    assert fake.clears == 1


def test_stop_stops_publishing(fake, rig):
    bus, worker, got = rig
    worker.stop()
    assert not worker.is_running()
    bus.publish_frame(frame(1, seq=1))
    time.sleep(0.3)
    assert got == []
    assert fake.seen == []
