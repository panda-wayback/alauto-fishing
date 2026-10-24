"""AutoCastWorker 黑盒测试：总线 Input → CastPhase / 鼠标 Output。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from autofish.cast_calibration.circle import CastCircle
from autofish.events.bus import AutofishBus
from autofish.events.topics import CastPhase, Topic
from autofish.auto_cast import AutoCastWorker


class FakeMouse:
    def __init__(self):
        self.calls: list[bool] = []
        self.down = False

    @property
    def pressed(self) -> bool:
        return self.down

    def set_holding(self, holding: bool) -> None:
        holding = bool(holding)
        if holding != self.down:
            self.calls.append(holding)
            self.down = holding

    def force_release(self) -> None:
        if self.down:
            self.calls.append(False)
            self.down = False


CIRCLE = CastCircle(cx=0.5, cy=0.5, angle_deg=60.0, radius_ratio=0.35)


def make_worker(
    bus: AutofishBus,
    mouse: FakeMouse,
    *,
    cursor=(960.0, 540.0),
    screen=(1920, 1080),
    circle=CIRCLE,
    wait_lo=0.01,
    wait_hi=0.02,
    full_charge_s=0.05,
    hold_jitter_s=0.0,
    start_settle_s=0.0,
):
    return AutoCastWorker(
        bus,
        wait_lo_s=wait_lo,
        wait_hi_s=wait_hi,
        full_charge_s=full_charge_s,
        hold_jitter_s=hold_jitter_s,
        start_settle_s=start_settle_s,
        mouse=mouse,
        load_circle=lambda: circle,
        cursor_pos=lambda: cursor,
        screen_size=lambda: screen,
    )


def wait_phase(worker: AutoCastWorker, phase, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if worker.phase == phase:
            return True
        time.sleep(0.005)
    return False


def wait_event(kit, phase, detail=None, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in kit.events:
            if e.phase != phase:
                continue
            if detail is None or e.detail == detail or detail in (e.detail or ""):
                return e
        time.sleep(0.005)
    return None


@pytest.fixture
def kit():
    bus = AutofishBus()
    mouse = FakeMouse()
    events: list = []
    bus.subscribe(Topic.CAST_PHASE, events.append)
    return SimpleNamespace(bus=bus, mouse=mouse, events=events)


def test_start_batch_settle_before_aim(kit):
    w = make_worker(
        kit.bus, kit.mouse, start_settle_s=0.15, wait_lo=0.01, wait_hi=0.02
    )
    w.start()
    try:
        assert w.start_batch(1) is True
        settle = wait_event(kit, CastPhase.WAIT, "settle", timeout=2.0)
        assert settle is not None and "wait=" in settle.detail
        assert wait_event(kit, CastPhase.CHARGING, timeout=2.0) is not None
    finally:
        w.stop()


def test_start_batch_aims_first_and_cancel_releases(kit):
    w = make_worker(kit.bus, kit.mouse, circle=None, wait_lo=0.2, wait_hi=0.3)
    w.start()
    try:
        assert w.start_batch(3) is True
        assert w.active and w.remaining == 3
        assert wait_event(kit, CastPhase.AIM, timeout=2.0)
        abort = wait_event(kit, CastPhase.ABORT, timeout=2.0)
        assert abort is not None and "no_calibration" in abort.detail
        waits = [e for e in kit.events if e.phase == CastPhase.WAIT]
        assert waits and all(e.detail.startswith("retry") for e in waits)

        assert w.start_batch(2) is False

        w.cancel_batch()
        assert wait_phase(w, CastPhase.DISABLED)
        assert not w.active and w.remaining == 0
        assert not kit.mouse.down
    finally:
        w.stop()


def test_aim_target_from_cursor_and_timed_charge(kit):
    center = (0.5 * 1920, 0.5 * 1080)
    w = make_worker(kit.bus, kit.mouse, cursor=center, full_charge_s=0.05)
    w.start()
    try:
        assert w.start_batch(1)
        charging = wait_event(kit, CastPhase.CHARGING, timeout=2.0)
        assert charging is not None
        assert "#1/1" in charging.detail
        assert "hold=" in charging.detail
        assert w.last_hold_s is not None and w.last_hold_s >= 0.02
        assert wait_event(kit, CastPhase.DONE, "reached", timeout=2.0)
        done = [e for e in kit.events if e.phase == CastPhase.DONE][-1]
        assert done.target == pytest.approx(0.0, abs=1e-6)
        assert done.power == pytest.approx(0.0, abs=1e-6)
        assert kit.mouse.calls[0] is True
        assert kit.mouse.calls[-1] is False
        assert wait_phase(w, CastPhase.DISABLED, timeout=2.0)
        assert not w.active and w.remaining == 0
    finally:
        w.stop()


def test_charge_hold_scales_with_full_charge(kit):
    # 环上点 → target≈1；full_charge 短则很快 DONE
    w = make_worker(
        kit.bus, kit.mouse,
        cursor=(1500.0, 540.0),
        full_charge_s=0.05,
    )
    w.start()
    try:
        t0 = time.time()
        assert w.start_batch(1)
        assert wait_event(kit, CastPhase.DONE, "reached", timeout=2.0)
        elapsed = time.time() - t0
        assert elapsed < 1.0
        done = [e for e in kit.events if e.phase == CastPhase.DONE][-1]
        assert done.target is not None and done.target > 0.2
        assert not kit.mouse.down
    finally:
        w.stop()


def test_cancel_during_charge_releases(kit):
    w = make_worker(
        kit.bus, kit.mouse,
        cursor=(1500.0, 540.0),
        full_charge_s=2.0,
    )
    w.start()
    try:
        assert w.start_batch(1)
        assert wait_phase(w, CastPhase.CHARGING, timeout=2.0)
        assert kit.mouse.down
        w.cancel_batch()
        assert wait_phase(w, CastPhase.DISABLED, timeout=2.0)
        assert not kit.mouse.down
        assert not w.active
    finally:
        w.stop()


def test_system_right_click_cancels_batch(kit):
    right = {"down": False}
    w = AutoCastWorker(
        kit.bus,
        wait_lo_s=0.01,
        wait_hi_s=0.02,
        full_charge_s=2.0,
        hold_jitter_s=0.0,
        start_settle_s=0.0,
        mouse=kit.mouse,
        load_circle=lambda: CIRCLE,
        cursor_pos=lambda: (1500.0, 540.0),
        screen_size=lambda: (1920, 1080),
        right_down=lambda: right["down"],
    )
    w.start()
    try:
        assert w.start_batch(2)
        w._ignore_right_until = 0.0
        assert wait_phase(w, CastPhase.CHARGING, timeout=2.0)
        right["down"] = True
        assert wait_event(kit, CastPhase.DISABLED, "right_click", timeout=2.0)
        assert not w.active and w.remaining == 0
        assert not kit.mouse.down
    finally:
        w.stop()


def test_missing_calibration_aborts(kit):
    w = make_worker(kit.bus, kit.mouse, circle=None)
    w.start()
    try:
        assert w.start_batch(1)
        assert wait_event(kit, CastPhase.ABORT, "no_calibration", timeout=2.0)
        assert True not in kit.mouse.calls
    finally:
        w.stop()


def test_missing_cursor_aborts(kit):
    w = make_worker(kit.bus, kit.mouse, cursor=None)
    w.start()
    try:
        assert w.start_batch(1)
        assert wait_event(kit, CastPhase.ABORT, "no_cursor", timeout=2.0)
    finally:
        w.stop()


def test_hook_blocks_next_cast_until_bobber(kit):
    """鱼钩（非就绪）时不抛下一杆；回到鱼漂才抛，且不记 no_fish。"""
    ready = {"on": True, "saw_done": False}

    def cast_ready() -> bool:
        if any(e.phase == CastPhase.DONE for e in kit.events):
            ready["saw_done"] = True
        if ready["saw_done"]:
            return ready["on"]
        return True

    w = make_worker(
        kit.bus,
        kit.mouse,
        cursor=(960.0, 540.0),
        full_charge_s=0.05,
        wait_lo=0.01,
        wait_hi=0.02,
    )
    w.set_cast_ready(cast_ready)
    ready["on"] = False
    w.start()
    try:
        assert w.start_batch(2)
        assert wait_event(kit, CastPhase.DONE, "reached", timeout=2.0)
        assert w.remaining == 1
        time.sleep(0.3)
        assert w.cast_index == 1
        assert not any(e.phase == CastPhase.CHARGING and "#2/2" in (e.detail or "") for e in kit.events)
        assert not any("no_fish" in (e.detail or "") for e in kit.events)
        bobber_wait = wait_event(kit, CastPhase.WAIT, "wait_bobber", timeout=1.0)
        assert bobber_wait is not None
        ready["on"] = True
        assert wait_event(kit, CastPhase.CHARGING, "#2/2", timeout=2.0)
    finally:
        w.stop()


def test_not_ready_blocks_first_cast(kit):
    ready = {"on": False}
    w = make_worker(
        kit.bus, kit.mouse, cursor=(960.0, 540.0), full_charge_s=0.05
    )
    w.set_cast_ready(lambda: ready["on"])
    w.start()
    try:
        assert w.start_batch(1)
        time.sleep(0.15)
        assert not any(e.phase == CastPhase.AIM for e in kit.events)
        ready["on"] = True
        assert wait_event(kit, CastPhase.CHARGING, timeout=2.0)
    finally:
        w.stop()


def test_batch_exhausts_and_finishes(kit):
    w = make_worker(
        kit.bus, kit.mouse, cursor=(960.0, 540.0),
        full_charge_s=0.05, wait_lo=0.01, wait_hi=0.02,
    )
    w.start()
    try:
        assert w.start_batch(2)
        assert wait_event(kit, CastPhase.DONE, "reached", timeout=2.0)
        assert wait_event(kit, CastPhase.DONE, "reached", timeout=2.0)
        assert wait_phase(w, CastPhase.DISABLED, timeout=2.0)
        assert not w.active and w.remaining == 0
        assert wait_event(kit, CastPhase.DISABLED, "batch_done", timeout=1.0)
    finally:
        w.stop()


def test_set_wait_range_clamps_and_swaps():
    w = make_worker(AutofishBus(), FakeMouse())
    w.set_wait_range(8.0, 1.0)
    assert (w._wait_lo, w._wait_hi) == (1.0, 8.0)
    w.set_wait_range(-5.0, 999.0)
    assert (w._wait_lo, w._wait_hi) == (0.0, 30.0)


def test_set_full_charge_s_clamps():
    w = make_worker(AutofishBus(), FakeMouse())
    w.set_full_charge_s(0.01)
    assert w.full_charge_s == pytest.approx(0.05)
    w.set_full_charge_s(9.0)
    assert w.full_charge_s == pytest.approx(5.0)


def test_stop_releases_mouse_and_thread_ends(kit):
    w = make_worker(
        kit.bus, kit.mouse,
        cursor=(1500.0, 540.0), full_charge_s=2.0,
    )
    w.start()
    assert w.start_batch(1)
    assert wait_phase(w, CastPhase.CHARGING, timeout=2.0)
    assert kit.mouse.down
    w.stop(timeout=2.0)
    assert not w.is_running()
    assert not kit.mouse.down
    assert not w.active
