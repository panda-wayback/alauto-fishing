"""段5：ActWorker — 订 ActionIntent → 真鼠标。"""

from __future__ import annotations

from autofish.act.mouse import MouseActuator, os_left_down
from autofish.bus import AutofishBus
from autofish.topics import ActionIntentEvent, FishingState, Topic


class ActWorker:
    """
    执行订阅者：只跟意图，不决策。
    优先级：系统左键 > 程序。系统按下且非本程序按下 → 让位，
    直到系统松开后才按快照意图接管。
    FISHING 才控鼠；单帧无 Pos 不松手；非钓鱼态 = 自由态。
    """

    def __init__(self, bus: AutofishBus) -> None:
        self.bus = bus
        self._mouse = MouseActuator()
        self._active = False
        self._yield_to_system = False

    @property
    def pressed(self) -> bool:
        return self._mouse.pressed

    @property
    def yielding(self) -> bool:
        """是否因系统占用而让位。"""
        return self._yield_to_system

    def start(self) -> None:
        if self._active:
            return
        self.bus.subscribe(Topic.ACTION_INTENT, self._on_intent)
        self._active = True
        self.poll()

    def stop(self) -> None:
        if not self._active:
            return
        self.bus.unsubscribe(Topic.ACTION_INTENT, self._on_intent)
        self._active = False
        self._yield_to_system = False
        self._mouse.force_release()

    def poll(self) -> None:
        """每帧调用：系统松开后立刻按当前意图接管。"""
        if self._active:
            self._apply_snapshot()

    def _apply_snapshot(self) -> None:
        snap = self.bus.snapshot()
        self._apply(snap.holding, snap.fishing_state)

    @staticmethod
    def _in_fishing(state: FishingState) -> bool:
        return state == FishingState.FISHING

    def _system_owns(self) -> bool:
        """系统按下且不是本程序按的 → 系统占用。"""
        os_down = os_left_down()
        if os_down is None:
            return False
        return bool(os_down) and not self._mouse.pressed

    def _apply(
        self,
        holding: bool | None,
        state: FishingState,
    ) -> None:
        if self._system_owns():
            self._yield_to_system = True
            return

        was_yielding = self._yield_to_system
        self._yield_to_system = False

        if not self._in_fishing(state):
            # 自由态：若我们正按着则松一次
            if self._mouse.pressed:
                self._mouse.set_holding(False)
            return

        if holding is True:
            self._mouse.set_holding(True)
        elif holding is False:
            self._mouse.set_holding(False)
        elif was_yielding:
            return

    def _on_intent(self, event: ActionIntentEvent) -> None:
        snap = self.bus.snapshot()
        self._apply(event.holding, snap.fishing_state)
