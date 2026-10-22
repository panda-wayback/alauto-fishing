import dataclasses
import threading
import time

import numpy as np
import pytest

from autofish.events.bus import AutofishBus
from autofish.events.topics import (
    ActionIntentEvent,
    BobberHit,
    CastPhase,
    CastPhaseEvent,
    CastSessionEvent,
    CastSessionState,
    FishingState,
    FishingStateEvent,
    FrameEvent,
    PosEvent,
    PressIntervalEvent,
    RoiEvent,
    SplashHit,
    Topic,
)
from autofish.events.worker_base import WorkerBase
from autofish.locate import Roi

ROI_A = Roi(left=0, top=0, width=100, height=20)
ROI_B = Roi(left=5, top=5, width=200, height=40)
FRAME = np.zeros((20, 100, 3), dtype=np.uint8)


def roi_event(version, roi=ROI_A, source="manual", score=1.0):
    return RoiEvent(roi=roi, version=version, ts=time.time(), source=source, score=score)


def frame_event(version, seq=1, ts=1.0):
    return FrameEvent(frame=FRAME, roi_version=version, ts=ts, seq=seq)


def pos_event(version, seq, pos=50.0):
    hit = BobberHit(pos=pos, x=10.0, y=5.0, pixel_count=9, bar_width=80.0)
    return PosEvent(
        pos=pos, hit=hit, roi_version=version, frame_ts=1.0, ts=2.0, frame_seq=seq
    )


def recorder(bus, topic):
    got = []
    bus.subscribe(topic, got.append)
    return got


def test_payloads_frozen_and_enums_are_strings():
    ev = ActionIntentEvent(holding=True, ts=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.holding = False  # type: ignore[misc]
    assert Topic.POS == "pos"
    assert Topic.ACTION_INTENT == "action_intent"
    assert FishingState.FISHING == "fishing"
    assert CastSessionState.DISABLED == "disabled"
    assert {t.value for t in Topic} == {
        "roi",
        "frame",
        "pos",
        "fishing_state",
        "cast_session",
        "cast_phase",
        "action_intent",
        "press_interval",
    }


def test_subscribe_publish_unsubscribe_and_isolation():
    bus = AutofishBus()
    got = recorder(bus, Topic.ACTION_INTENT)
    others = recorder(bus, Topic.POS)

    def boom(_):
        raise RuntimeError("boom")

    bus.subscribe(Topic.ACTION_INTENT, boom)
    later = recorder(bus, Topic.ACTION_INTENT)
    ev = ActionIntentEvent(holding=True, ts=1.0, reason="r")
    bus.publish_action_intent(ev)
    assert got == [ev] and later == [ev]
    assert got[0] is ev
    assert others == []

    bus.unsubscribe(Topic.ACTION_INTENT, got.append)
    bus.publish_action_intent(ActionIntentEvent(holding=False, ts=2.0))
    assert len(got) == 1 and len(later) == 2


def test_new_bus_snapshot_defaults():
    bus = AutofishBus()
    snap = bus.snapshot()
    assert bus.current_roi() == (None, 0)
    assert snap.roi is None and snap.roi_version == 0
    assert snap.frame is None and snap.pos is None and snap.hit is None
    assert snap.fishing_state == FishingState.IDLE
    assert snap.cast_session == CastSessionState.DISABLED
    assert snap.holding is None
    assert snap.press_interval_s == 0.0


def test_publish_roi_updates_current_and_snapshot():
    bus = AutofishBus()
    got = recorder(bus, Topic.ROI)
    ev = roi_event(3, score=0.7, source="default")
    bus.publish_roi(ev)
    assert got == [ev]
    assert bus.current_roi() == (ROI_A, 3)
    snap = bus.snapshot()
    assert (snap.roi, snap.roi_version, snap.roi_source, snap.roi_score) == (
        ROI_A, 3, "default", 0.7,
    )


def test_publish_frame_version_gate_and_snapshot_has_no_frame():
    bus = AutofishBus()
    got = recorder(bus, Topic.FRAME)
    bus.publish_roi(roi_event(1))
    ok = frame_event(1, ts=12.5)
    bus.publish_frame(ok)
    bus.publish_frame(frame_event(2, seq=2, ts=99.0))
    assert got == [ok]
    snap = bus.snapshot()
    assert snap.frame_ts == 12.5
    assert snap.frame is None


def test_roi_version_change_invalidates_old_frames_and_pos():
    bus = AutofishBus()
    frames = recorder(bus, Topic.FRAME)
    poses = recorder(bus, Topic.POS)
    bus.publish_roi(roi_event(1))
    bus.publish_frame(frame_event(1, seq=1))
    bus.publish_pos(pos_event(1, seq=1, pos=40.0))

    bus.publish_roi(roi_event(2, roi=ROI_B))
    assert bus.snapshot().frame_ts == 0.0
    bus.publish_frame(frame_event(1, seq=2))
    bus.publish_pos(pos_event(1, seq=2, pos=41.0))
    assert len(frames) == 1 and len(poses) == 1
    assert bus.snapshot().pos == 40.0

    bus.publish_frame(frame_event(2, seq=3))
    bus.publish_pos(pos_event(2, seq=3, pos=60.0))
    assert [f.roi_version for f in frames] == [1, 2]
    assert [p.pos for p in poses] == [40.0, 60.0]
    assert bus.snapshot().pos == 60.0


def test_publish_pos_seq_order_and_reset():
    bus = AutofishBus()
    poses = recorder(bus, Topic.POS)
    bus.publish_roi(roi_event(1))
    bus.publish_pos(pos_event(1, seq=5, pos=10.0))
    bus.publish_pos(pos_event(1, seq=4, pos=20.0))  # 旧帧序丢弃
    bus.publish_pos(pos_event(1, seq=5, pos=30.0))  # 相等接受
    assert [p.pos for p in poses] == [10.0, 30.0]
    snap = bus.snapshot()
    assert (snap.pos, snap.pos_frame_seq) == (30.0, 5)
    assert snap.hit is not None and snap.hit.pos == 30.0

    bus.reset_pos_seq()
    snap = bus.snapshot()
    assert (snap.pos, snap.hit, snap.pos_frame_seq) == (None, None, 0)
    assert len(poses) == 2  # 重置不推送
    bus.publish_pos(pos_event(1, seq=1, pos=70.0))
    assert bus.snapshot().pos == 70.0


def test_state_and_cast_session_dedup():
    bus = AutofishBus()
    states = recorder(bus, Topic.FISHING_STATE)
    casts = recorder(bus, Topic.CAST_SESSION)

    bus.publish_fishing_state(FishingStateEvent(state=FishingState.IDLE, ts=1.0))
    assert states == []  # 与初值相同
    bus.publish_fishing_state(FishingStateEvent(state=FishingState.FISHING, ts=2.0, detail="a"))
    bus.publish_fishing_state(FishingStateEvent(state=FishingState.FISHING, ts=3.0, detail="a"))
    bus.publish_fishing_state(FishingStateEvent(state=FishingState.FISHING, ts=4.0, detail="b"))
    assert [(e.detail, e.ts) for e in states] == [("a", 2.0), ("b", 4.0)]
    snap = bus.snapshot()
    assert (snap.fishing_state, snap.fishing_detail, snap.state_ts) == (
        FishingState.FISHING, "b", 4.0,
    )

    splash = SplashHit(score=0.9, delay_s=0.1, hold_s=0.2, after_s=0.3, threshold=0.5)
    bus.publish_cast_session(CastSessionEvent(state=CastSessionState.DISABLED, ts=1.0))
    bus.publish_cast_session(CastSessionEvent(state=CastSessionState.WAIT, ts=2.0))
    bus.publish_cast_session(CastSessionEvent(state=CastSessionState.WAIT, ts=3.0))
    bus.publish_cast_session(
        CastSessionEvent(state=CastSessionState.FIRST_CLICK, ts=4.0, splash=splash)
    )
    bus.publish_cast_session(
        CastSessionEvent(state=CastSessionState.FIRST_CLICK, ts=5.0, splash=splash)
    )
    assert [e.state for e in casts] == [CastSessionState.WAIT, CastSessionState.FIRST_CLICK]
    snap = bus.snapshot()
    assert snap.cast_session == CastSessionState.FIRST_CLICK
    assert snap.cast_splash == splash and snap.cast_ts == 4.0


def test_cast_phase_dedup():
    bus = AutofishBus()
    got = recorder(bus, Topic.CAST_PHASE)
    assert bus.snapshot().cast_phase == CastPhase.DISABLED

    bus.publish_cast_phase(CastPhaseEvent(phase=CastPhase.WAIT, ts=1.0))
    bus.publish_cast_phase(CastPhaseEvent(phase=CastPhase.WAIT, ts=2.0))
    bus.publish_cast_phase(CastPhaseEvent(phase=CastPhase.WAIT, ts=3.0, detail="next"))
    bus.publish_cast_phase(
        CastPhaseEvent(phase=CastPhase.CHARGING, ts=4.0, target=0.5, power=0.1)
    )

    assert [(e.phase, e.detail) for e in got] == [
        (CastPhase.WAIT, ""),
        (CastPhase.WAIT, "next"),
        (CastPhase.CHARGING, ""),
    ]
    snap = bus.snapshot()
    assert snap.cast_phase == CastPhase.CHARGING
    assert snap.cast_phase_detail == ""
    assert snap.cast_ts == 4.0


def test_action_intent_not_deduplicated():
    bus = AutofishBus()
    got = recorder(bus, Topic.ACTION_INTENT)
    for i in range(3):
        bus.publish_action_intent(ActionIntentEvent(holding=True, ts=float(i), reason=f"r{i}"))
    assert len(got) == 3
    snap = bus.snapshot()
    assert (snap.holding, snap.intent_reason, snap.intent_ts) == (True, "r2", 2.0)


@pytest.mark.parametrize("raw,clamped", [(-1.0, 0.0), (0.12, 0.12), (5.0, 0.3)])
def test_press_interval_clamped(raw, clamped):
    bus = AutofishBus()
    got = recorder(bus, Topic.PRESS_INTERVAL)
    bus.publish_press_interval(PressIntervalEvent(interval_s=raw, ts=7.0))
    assert len(got) == 1
    assert got[0].interval_s == pytest.approx(clamped) and got[0].ts == 7.0
    assert bus.snapshot().press_interval_s == pytest.approx(clamped)


def test_clear_roi_bumps_version():
    bus = AutofishBus()
    got = recorder(bus, Topic.ROI)
    bus.publish_roi(roi_event(4))
    bus.clear_roi("manual")
    ev = got[-1]
    assert (ev.roi, ev.version, ev.source) == (None, 5, "manual")
    assert bus.current_roi() == (None, 5)
    bus.clear_roi()
    assert (got[-1].version, got[-1].source) == (6, "clear")


def test_snapshot_is_a_copy():
    bus = AutofishBus()
    bus.publish_roi(roi_event(1))
    snap = bus.snapshot()
    snap.roi_version = 99
    snap.holding = True
    again = bus.snapshot()
    assert again.roi_version == 1 and again.holding is None


class LoopWorker(WorkerBase):
    def __init__(self, bus):
        super().__init__(bus, "test-loop")
        self.started = 0

    def _run(self):
        self.started += 1
        while not self._stop.is_set():
            self._stop.wait(0.01)


class StubbornWorker(WorkerBase):
    """忽略停止标志，直到 release 被置位。"""

    def __init__(self, bus):
        super().__init__(bus, "test-stubborn")
        self.release = threading.Event()

    def _run(self):
        self.release.wait(5.0)


def wait_until(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_worker_start_stop_restart():
    w = LoopWorker(AutofishBus())
    assert not w.is_running()
    try:
        w.start()
        assert w.is_running()
        w.start()
        assert wait_until(lambda: w.started == 1)
        w.stop(timeout=1.0)
        assert not w.is_running()
        w.start()
        assert w.is_running()
        assert wait_until(lambda: w.started == 2)
    finally:
        w.stop(timeout=1.0)
    assert not w.is_running()


def test_worker_stop_timeout_keeps_running_true():
    w = StubbornWorker(AutofishBus())
    try:
        w.start()
        w.stop(timeout=0.05)
        assert w.is_running()
    finally:
        w.release.set()
    w.stop(timeout=2.0)
    assert not w.is_running()
