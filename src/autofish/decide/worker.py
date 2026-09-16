"""段4：DecideWorker — 订 Pos → 发 ActionIntent。"""

from __future__ import annotations

import time

from autofish.bus import AutofishBus
from autofish.decide.policy import ThresholdPosPolicy
from autofish.topics import (
    ActionIntentEvent,
    FishingState,
    FishingStateEvent,
    PosEvent,
    Topic,
)


class DecideWorker:
    """策略订阅者：不截屏、不点鼠标。"""

    def __init__(
        self,
        bus: AutofishBus,
        *,
        low: float = 50.0,
        high: float = 80.0,
    ) -> None:
        self.bus = bus
        self._policy = ThresholdPosPolicy(low=low, high=high)
        self._t0 = time.perf_counter()
        self._state = FishingState.IDLE
        self._last_holding: bool | None = None
        self._active = False

    def set_thresholds(self, low: float, high: float) -> None:
        if low >= high:
            raise ValueError("low must be < high")
        self._policy.low = float(low)
        self._policy.high = float(high)

    def start(self) -> None:
        if self._active:
            return
        self._t0 = time.perf_counter()
        self._policy.reset()
        self._last_holding = None
        self.bus.subscribe(Topic.POS, self._on_pos)
        self.bus.subscribe(Topic.FISHING_STATE, self._on_state)
        self._active = True
        # 立刻按当前快照出意图，避免「已有 POS 但要等下一次变化才控鼠」
        self._sync_from_snapshot()

    def stop(self) -> None:
        if not self._active:
            return
        self.bus.unsubscribe(Topic.POS, self._on_pos)
        self.bus.unsubscribe(Topic.FISHING_STATE, self._on_state)
        self._active = False
        self._emit(False, "decide_stop", None)

    def _now(self) -> float:
        return time.perf_counter() - self._t0

    def _sync_from_snapshot(self) -> None:
        snap = self.bus.snapshot()
        self._state = snap.fishing_state
        self._apply_pos(snap.pos)

    def _on_state(self, event: FishingStateEvent) -> None:
        self._state = event.state
        if event.state != FishingState.FISHING:
            self._policy.reset()
            self._emit(False, f"state_{event.state.value}", None)

    def _on_pos(self, event: PosEvent) -> None:
        self._apply_pos(event.pos)

    def _apply_pos(self, pos: float | None) -> None:
        if self._state != FishingState.FISHING or pos is None:
            self._emit(False, "no_pos", pos)
            return
        holding, reason = self._policy.decide(pos, self._now())
        self._emit(holding, reason, pos)

    def _emit(self, holding: bool, reason: str, pos: float | None) -> None:
        if self._last_holding is not None and holding == self._last_holding:
            return
        self._last_holding = holding
        self.bus.publish_action_intent(
            ActionIntentEvent(
                holding=holding,
                ts=time.time(),
                reason=reason,
                pos=pos,
            )
        )
