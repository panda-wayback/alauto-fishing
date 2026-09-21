"""段5：ActWorker — 订 ActionIntent / PressInterval → 真鼠标。"""

from __future__ import annotations

import time

from autofish.act.mouse import MouseActuator, os_left_down
from autofish.bus import AutofishBus
from autofish.topics import (
    ActionIntentEvent,
    CastSessionEvent,
    CastSessionState,
    FishingState,
    PressIntervalEvent,
    Topic,
)

_DEFAULT_PRESS_INTERVAL = 0.0
_MAX_PRESS_INTERVAL = 0.3


class ActWorker:
    """
    执行订阅者：只跟意图，不决策。
    按下受 press_interval 门控；松开立刻。
    优先级：系统左键 > 程序。系统按下且非本程序按下 → 让位，
    直到系统松开后才按快照意图接管。
    A 关：鱼漂 FISHING 才控鼠；A 开：仅会话 FISHING（第一下/等漂不抢键）。
    单帧无 Pos 不松手；非可控鼠 = 自由态（松手）。
    """

    def __init__(self, bus: AutofishBus) -> None:
        self.bus = bus
        self._mouse = MouseActuator()
        self._active = False
        self._yield_to_system = False
        self._press_interval = _DEFAULT_PRESS_INTERVAL
        self._last_press_at = 0.0
        # 间隔主题始终订：壳可在操作未启用时先调
        self.bus.subscribe(Topic.PRESS_INTERVAL, self._on_press_interval)

    @property
    def pressed(self) -> bool:
        return self._mouse.pressed

    @property
    def yielding(self) -> bool:
        """是否因系统占用而让位。"""
        return self._yield_to_system

    @property
    def press_interval(self) -> float:
        return self._press_interval

    def start(self) -> None:
        if self._active:
            return
        self._press_interval = self.bus.snapshot().press_interval_s
        self.bus.subscribe(Topic.ACTION_INTENT, self._on_intent)
        self.bus.subscribe(Topic.CAST_SESSION, self._on_cast)
        self._active = True
        self.poll()

    def stop(self) -> None:
        if not self._active:
            return
        self.bus.unsubscribe(Topic.ACTION_INTENT, self._on_intent)
        self.bus.unsubscribe(Topic.CAST_SESSION, self._on_cast)
        self._active = False
        self._yield_to_system = False
        self._mouse.force_release()

    def poll(self) -> None:
        """每帧调用：系统松开后立刻按当前意图接管；补上被间隔挡住的按下。"""
        if self._active:
            self._apply_snapshot()

    def _apply_snapshot(self) -> None:
        snap = self.bus.snapshot()
        self._apply(snap.holding, snap)

    @staticmethod
    def _may_control(snap) -> bool:
        """A 关：跟鱼漂 FSM；A 开：仅会话 FISHING。"""
        if snap.cast_session == CastSessionState.DISABLED:
            return snap.fishing_state == FishingState.FISHING
        return snap.cast_session == CastSessionState.FISHING

    def _system_owns(self) -> bool:
        """系统按下且不是本程序按的 → 系统占用。"""
        os_down = os_left_down()
        if os_down is None:
            return False
        return bool(os_down) and not self._mouse.pressed

    def _release_program(self) -> None:
        self._yield_to_system = False
        if self._mouse.pressed:
            self._mouse.set_holding(False)

    def _on_cast(self, event: CastSessionEvent) -> None:
        """会话离开 FISHING（含进入 FIRST_CLICK）→ 立刻松本段落键，让出第一下。"""
        if not self._active:
            return
        snap = self.bus.snapshot()
        # 快照可能已更新；以事件态为准判断是否仍可拉
        if event.state == CastSessionState.DISABLED:
            if snap.fishing_state != FishingState.FISHING:
                self._release_program()
            return
        if event.state != CastSessionState.FISHING:
            self._release_program()

    def _apply(
        self,
        holding: bool | None,
        snap,
    ) -> None:
        # 无权控鼠时优先松手（即使开钓第一下正按着系统键，也只清本段键态）
        if not self._may_control(snap):
            self._release_program()
            return

        if self._system_owns():
            self._yield_to_system = True
            return

        was_yielding = self._yield_to_system
        self._yield_to_system = False

        if holding is True:
            self._try_press()
        elif holding is False:
            self._mouse.set_holding(False)
        elif was_yielding:
            return

    def _try_press(self) -> None:
        if self._mouse.pressed:
            return
        now = time.monotonic()
        if now - self._last_press_at < self._press_interval:
            return
        self._mouse.set_holding(True)
        self._last_press_at = now

    def _on_intent(self, event: ActionIntentEvent) -> None:
        snap = self.bus.snapshot()
        self._apply(event.holding, snap)

    def _on_press_interval(self, event: PressIntervalEvent) -> None:
        self._press_interval = max(
            0.0, min(_MAX_PRESS_INTERVAL, float(event.interval_s))
        )
