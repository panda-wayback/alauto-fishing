import time

import pytest

from autofish.decide import DecideWorker, ThresholdPosPolicy
from autofish.events.bus import AutofishBus
from autofish.events.topics import (
    ActionIntentEvent,
    CastSessionEvent,
    CastSessionState,
    FishingState,
    FishingStateEvent,
    PosEvent,
    Topic,
)

# 退化范围：low 固定 40、high 固定 60
FIXED = dict(press_lo=40.0, press_hi=40.0, release_lo=60.0, release_hi=60.0)


def pos_event(pos, seq=[0]):
    seq[0] += 1
    now = time.time()
    return PosEvent(pos=pos, hit=None, roi_version=0, frame_ts=now, ts=now, frame_seq=seq[0])


def set_state(bus, state):
    bus.publish_fishing_state(FishingStateEvent(state=state, ts=time.time()))


def set_cast(bus, state):
    bus.publish_cast_session(CastSessionEvent(state=state, ts=time.time()))


@pytest.fixture
def rig():
    bus = AutofishBus()
    intents: list[ActionIntentEvent] = []
    bus.subscribe(Topic.ACTION_INTENT, intents.append)
    worker = DecideWorker(bus, **FIXED)
    yield bus, worker, intents
    worker.stop()


# ---- ThresholdPosPolicy ----


def test_policy_default_thresholds_in_ranges():
    p = ThresholdPosPolicy(seed=1)
    assert 70.6 <= p.low <= 74.4
    assert 76.6 <= p.high <= 79.2


def test_policy_below_low_holds_above_high_releases_band_keeps():
    p = ThresholdPosPolicy(**FIXED)
    holding, reason = p.decide(50)
    assert holding is False and isinstance(reason, str) and reason
    assert p.decide(39.9)[0] is True
    assert p.decide(50)[0] is True
    assert p.decide(40)[0] is True
    assert p.decide(60)[0] is True
    assert p.decide(60.1)[0] is False
    assert p.decide(50)[0] is False


def test_policy_resamples_within_ranges_after_switch():
    p = ThresholdPosPolicy(press_lo=10, press_hi=30, release_lo=70, release_hi=90, seed=3)
    seen = set()
    for i in range(40):
        p.decide(0 if i % 2 == 0 else 100)
        assert 10 <= p.low <= 30 and 70 <= p.high <= 90
        seen.add((p.low, p.high))
    assert len(seen) > 1


def test_policy_same_seed_is_deterministic():
    a = ThresholdPosPolicy(seed=42)
    b = ThresholdPosPolicy(seed=42)
    for pos in [0, 100, 0, 100, 75, 0]:
        assert a.decide(pos) == b.decide(pos)
        assert (a.low, a.high) == (b.low, b.high)


def test_policy_reset_releases():
    p = ThresholdPosPolicy(**FIXED)
    assert p.decide(0)[0] is True
    p.reset()
    assert p.decide(50)[0] is False


def test_policy_set_ranges_applies_and_validates():
    p = ThresholdPosPolicy()
    p.set_ranges(20, 20, 30, 30)
    assert (p.low, p.high) == (20.0, 30.0)
    assert (p.press_lo, p.press_hi, p.release_lo, p.release_hi) == (20.0, 20.0, 30.0, 30.0)
    with pytest.raises(ValueError):
        p.set_ranges(50, 40, 60, 70)
    with pytest.raises(ValueError):
        p.set_ranges(40, 50, 70, 60)
    with pytest.raises(ValueError):
        p.set_ranges(40, 60, 60, 70)
    with pytest.raises(ValueError):
        ThresholdPosPolicy(press_lo=80, press_hi=90, release_lo=70, release_hi=75)


# ---- DecideWorker ----


def test_worker_thresholds_and_set_ranges():
    w = DecideWorker(AutofishBus())
    low, high = w.current_thresholds
    assert 70.6 <= low <= 74.4 and 76.6 <= high <= 79.2
    w.set_ranges(10, 10, 20, 20)
    assert w.current_thresholds == (10.0, 20.0)
    with pytest.raises(ValueError):
        w.set_ranges(30, 30, 20, 20)


def test_worker_start_when_idle_publishes_release(rig):
    bus, worker, intents = rig
    worker.start()
    assert [e.holding for e in intents] == [False]


def test_worker_fishing_pos_drives_intents(rig):
    bus, worker, intents = rig
    worker.start()
    set_state(bus, FishingState.FISHING)
    intents.clear()
    bus.publish_pos(pos_event(10))
    assert [e.holding for e in intents] == [True]
    assert intents[-1].pos == 10 and intents[-1].reason
    bus.publish_pos(pos_event(20))
    bus.publish_pos(pos_event(50))
    assert len(intents) == 1
    bus.publish_pos(pos_event(90))
    assert [e.holding for e in intents] == [True, False]


def test_worker_missing_pos_keeps_last_intent(rig):
    bus, worker, intents = rig
    worker.start()
    set_state(bus, FishingState.FISHING)
    bus.publish_pos(pos_event(10))
    intents.clear()
    bus.publish_pos(pos_event(None))
    assert intents == []


def test_worker_not_fishing_ignores_pos(rig):
    bus, worker, intents = rig
    worker.start()
    intents.clear()
    bus.publish_pos(pos_event(10))
    assert intents == []


def test_worker_leaving_fishing_forces_release(rig):
    bus, worker, intents = rig
    worker.start()
    set_state(bus, FishingState.FISHING)
    bus.publish_pos(pos_event(10))
    assert intents[-1].holding is True
    set_state(bus, FishingState.LOST)
    assert intents[-1].holding is False


def test_worker_reentering_fishing_uses_latest_pos(rig):
    bus, worker, intents = rig
    worker.start()
    bus.publish_pos(pos_event(10))
    intents.clear()
    set_state(bus, FishingState.FISHING)
    assert [e.holding for e in intents] == [True]


def test_worker_cast_on_only_holds_in_session_fishing(rig):
    bus, worker, intents = rig
    worker.start()
    set_state(bus, FishingState.FISHING)
    set_cast(bus, CastSessionState.WAIT_BOBBER)
    intents.clear()
    bus.publish_pos(pos_event(10))
    assert intents == []
    set_cast(bus, CastSessionState.FISHING)
    assert [e.holding for e in intents] == [True]


def test_worker_cast_leaving_fishing_forces_release(rig):
    bus, worker, intents = rig
    worker.start()
    set_cast(bus, CastSessionState.FISHING)
    bus.publish_pos(pos_event(10))
    assert intents[-1].holding is True
    set_cast(bus, CastSessionState.FIRST_CLICK)
    assert intents[-1].holding is False
    intents.clear()
    bus.publish_pos(pos_event(10))
    assert intents == []


def test_worker_start_syncs_from_snapshot(rig):
    bus, worker, intents = rig
    set_state(bus, FishingState.FISHING)
    bus.publish_pos(pos_event(10))
    worker.start()
    assert [e.holding for e in intents] == [True]


def test_worker_stop_releases_and_unsubscribes(rig):
    bus, worker, intents = rig
    worker.start()
    set_state(bus, FishingState.FISHING)
    bus.publish_pos(pos_event(10))
    worker.stop()
    assert intents[-1].holding is False
    n = len(intents)
    bus.publish_pos(pos_event(90))
    bus.publish_pos(pos_event(10))
    assert len(intents) == n


def test_worker_start_stop_idempotent(rig):
    bus, worker, intents = rig
    worker.start()
    worker.start()
    set_state(bus, FishingState.FISHING)
    intents.clear()
    bus.publish_pos(pos_event(10))
    assert len(intents) == 1
    worker.stop()
    n = len(intents)
    worker.stop()
    assert len(intents) == n
