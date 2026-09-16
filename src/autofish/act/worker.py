"""段5：ActWorker — 订 ActionIntent → 真鼠标。"""

from __future__ import annotations

from autofish.act.mouse import MouseActuator
from autofish.bus import AutofishBus
from autofish.topics import ActionIntentEvent, Topic


class ActWorker:
    """执行订阅者：只跟意图，不决策。"""

    def __init__(self, bus: AutofishBus) -> None:
        self.bus = bus
        self._mouse = MouseActuator()
        self._active = False

    @property
    def pressed(self) -> bool:
        return self._mouse.pressed

    def start(self) -> None:
        if self._active:
            return
        self.bus.subscribe(Topic.ACTION_INTENT, self._on_intent)
        self._active = True

    def stop(self) -> None:
        if not self._active:
            return
        self.bus.unsubscribe(Topic.ACTION_INTENT, self._on_intent)
        self._active = False
        self._mouse.force_release()

    def _on_intent(self, event: ActionIntentEvent) -> None:
        self._mouse.set_holding(event.holding)
