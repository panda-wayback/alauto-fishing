import time

import pytest

import autofish.act.mouse as mouse_mod
import autofish.act.worker as worker_mod
from autofish.act import ActWorker, MouseActuator
from autofish.events.bus import AutofishBus
from autofish.events.topics import (
    ActionIntentEvent,
    CastPhase,
    CastPhaseEvent,
    CastSessionEvent,
    CastSessionState,
    FishingState,
    FishingStateEvent,
    PosEvent,
    PressIntervalEvent,
)


REAL_OS_LEFT_DOWN = mouse_mod.os_left_down
REAL_OS_RIGHT_DOWN = mouse_mod.os_right_down


def test_os_left_down_returns_bool_or_none():
    assert REAL_OS_LEFT_DOWN() in (True, False, None)


def test_os_right_down_returns_bool_or_none():
    assert REAL_OS_RIGHT_DOWN() in (True, False, None)


class FakeController:
    log: list = []

    def press(self, button):
        FakeController.log.append(("press", button))

    def release(self, button):
        FakeController.log.append(("release", button))


@pytest.fixture(autouse=True)
def no_real_mouse(monkeypatch):
    """替换 pynput 控制器与系统键态读取，绝不触碰真鼠标。"""
    FakeController.log = []
    os_state = {"down": False}
    monkeypatch.setattr(mouse_mod, "Controller", FakeController)
    monkeypatch.setattr(mouse_mod, "os_left_down", lambda: os_state["down"])
    monkeypatch.setattr(worker_mod, "os_left_down", lambda: os_state["down"])
    return os_state


def presses():
    return [a for a, _ in FakeController.log if a == "press"]


def releases():
    return [a for a, _ in FakeController.log if a == "release"]


def intent(bus, holding):
    bus.publish_action_intent(ActionIntentEvent(holding=holding, ts=time.time()))


def set_state(bus, state):
    bus.publish_fishing_state(FishingStateEvent(state=state, ts=time.time()))


def set_cast(bus, state):
    bus.publish_cast_session(CastSessionEvent(state=state, ts=time.time()))


def set_cast_phase(bus, phase, detail=""):
    bus.publish_cast_phase(CastPhaseEvent(phase=phase, ts=time.time(), detail=detail))


def set_interval(bus, seconds):
    bus.publish_press_interval(PressIntervalEvent(interval_s=seconds, ts=time.time()))


@pytest.fixture
def rig():
    bus = AutofishBus()
    worker = ActWorker(bus)
    yield bus, worker
    worker.stop()


# ---- MouseActuator ----


def test_actuator_press_release_once():
    from pynput.mouse import Button

    m = MouseActuator()
    assert m.pressed is False
    m.set_holding(True)
    m.set_holding(True)
    assert m.pressed is True
    m.set_holding(False)
    m.set_holding(False)
    assert m.pressed is False
    assert FakeController.log == [("press", Button.left), ("release", Button.left)]


def test_actuator_force_release_only_if_pressed():
    m = MouseActuator()
    m.force_release()
    assert FakeController.log == []
    m.set_holding(True)
    m.force_release()
    assert m.pressed is False and releases() == ["release"]


# ---- ActWorker ----


def test_worker_follows_intent_when_fishing(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    assert worker.pressed is True and presses() == ["press"]
    intent(bus, True)
    assert presses() == ["press"]
    intent(bus, False)
    assert worker.pressed is False and releases() == ["release"]


def test_worker_ignores_intent_before_start(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    intent(bus, True)
    assert worker.pressed is False and FakeController.log == []


def test_worker_start_applies_snapshot_intent(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    intent(bus, True)
    worker.start()
    assert worker.pressed is True


def test_worker_no_press_when_not_fishing(rig):
    bus, worker = rig
    worker.start()
    intent(bus, True)
    assert worker.pressed is False and FakeController.log == []


def test_worker_press_interval_gates_second_press(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    set_interval(bus, 0.15)
    assert worker.press_interval == pytest.approx(0.15)
    intent(bus, True)
    intent(bus, False)
    assert releases() == ["release"]
    intent(bus, True)
    assert worker.pressed is False and presses() == ["press"]
    worker.poll()
    assert worker.pressed is False
    time.sleep(0.2)
    worker.poll()
    assert worker.pressed is True and presses() == ["press", "press"]


def test_worker_release_is_immediate_despite_interval(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    set_interval(bus, 0.3)
    worker.start()
    intent(bus, True)
    intent(bus, False)
    assert worker.pressed is False and releases() == ["release"]


def test_press_interval_clamped_and_read_on_start():
    bus = AutofishBus()
    set_interval(bus, 0.12)
    worker = ActWorker(bus)
    try:
        worker.start()
        assert worker.press_interval == pytest.approx(0.12)
        set_interval(bus, 5.0)
        assert worker.press_interval == pytest.approx(0.3)
        set_interval(bus, -1.0)
        assert worker.press_interval == 0.0
    finally:
        worker.stop()


def test_press_interval_received_before_start():
    bus = AutofishBus()
    worker = ActWorker(bus)
    set_interval(bus, 0.2)
    assert worker.press_interval == pytest.approx(0.2)


def test_stopped_worker_is_not_retained_by_bus():
    import gc
    import weakref

    bus = AutofishBus()
    refs = []
    for _ in range(3):
        worker = ActWorker(bus)
        worker.start()
        worker.stop()
        refs.append(weakref.ref(worker))
        del worker
    gc.collect()
    assert all(r() is None for r in refs)


def test_worker_releases_on_entering_non_fishing_cast(rig):
    bus, worker = rig
    set_cast(bus, CastSessionState.FISHING)
    worker.start()
    intent(bus, True)
    assert worker.pressed is True
    set_cast(bus, CastSessionState.FIRST_CLICK)
    assert worker.pressed is False and releases() == ["release"]


def test_worker_cast_on_only_presses_in_session_fishing(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    set_cast(bus, CastSessionState.WAIT_BOBBER)
    worker.start()
    intent(bus, True)
    assert worker.pressed is False
    set_cast(bus, CastSessionState.FISHING)
    worker.poll()
    assert worker.pressed is True


def test_worker_cast_disabled_releases_if_bobber_not_fishing(rig):
    bus, worker = rig
    set_cast(bus, CastSessionState.FISHING)
    worker.start()
    intent(bus, True)
    set_cast(bus, CastSessionState.DISABLED)
    assert worker.pressed is False


def test_worker_releases_on_poll_after_leaving_fishing(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    set_state(bus, FishingState.LOST)
    worker.poll()
    assert worker.pressed is False


def test_worker_single_missing_pos_keeps_pressed(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    now = time.time()
    bus.publish_pos(
        PosEvent(pos=None, hit=None, roi_version=0, frame_ts=now, ts=now, frame_seq=1)
    )
    worker.poll()
    assert worker.pressed is True and releases() == []


def test_worker_yields_to_system_button_then_takes_over(rig, no_real_mouse):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    no_real_mouse["down"] = True
    intent(bus, True)
    assert worker.yielding is True and worker.pressed is False
    worker.poll()
    assert worker.yielding is True and FakeController.log == []
    no_real_mouse["down"] = False
    worker.poll()
    assert worker.yielding is False and worker.pressed is True


def test_worker_own_press_is_not_system_owned(rig, no_real_mouse):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    no_real_mouse["down"] = True
    intent(bus, False)
    assert worker.yielding is False and worker.pressed is False


def test_worker_no_yield_without_control(rig, no_real_mouse):
    bus, worker = rig
    worker.start()
    no_real_mouse["down"] = True
    intent(bus, True)
    worker.poll()
    assert worker.yielding is False and worker.pressed is False


def test_worker_unknown_os_state_does_not_yield(rig, monkeypatch):
    bus, worker = rig
    monkeypatch.setattr(worker_mod, "os_left_down", lambda: None)
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    assert worker.yielding is False and worker.pressed is True


def test_worker_stop_releases_and_unsubscribes(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    worker.stop()
    assert worker.pressed is False and releases() == ["release"]
    intent(bus, True)
    worker.poll()
    assert worker.pressed is False and presses() == ["press"]


def test_worker_yields_while_cast_charging(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    assert worker.pressed is True
    set_cast_phase(bus, CastPhase.CHARGING)
    assert worker.pressed is False
    worker.poll()
    assert worker.pressed is False


def test_worker_resumes_after_charging_ends(rig):
    bus, worker = rig
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    set_cast_phase(bus, CastPhase.CHARGING)
    assert worker.pressed is False
    set_cast_phase(bus, CastPhase.DONE)
    assert worker.pressed is True
    assert worker.yielding is False


def test_worker_does_not_press_when_charging_at_start(rig):
    bus, worker = rig
    set_cast_phase(bus, CastPhase.CHARGING)
    set_state(bus, FishingState.FISHING)
    worker.start()
    intent(bus, True)
    assert worker.pressed is False
