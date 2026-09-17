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
        press_lo: float = 40.0,
        press_hi: float = 70.0,
        release_lo: float = 75.0,
        release_hi: float = 90.0,
    ) -> None:
        self.bus = bus
        self._policy = ThresholdPosPolicy(
            press_lo=press_lo,
            press_hi=press_hi,
            release_lo=release_lo,
            release_hi=release_hi,
        )
        self._t0 = time.perf_counter()
        self._state = FishingState.IDLE
        self._last_holding: bool | None = None
        self._active = False

    def set_ranges(
        self,
        press_lo: float,
        press_hi: float,
        release_lo: float,
        release_hi: float,
    ) -> None:
        self._policy.set_ranges(press_lo, press_hi, release_lo, release_hi)

    @property
    def current_thresholds(self) -> tuple[float, float]:
        return self._policy.low, self._policy.high

    def start(self) -> None:
        if self._active:
            return
        self._t0 = time.perf_counter()
        self._policy.reset()
        self._last_holding = None
        self.bus.subscribe(Topic.POS, self._on_pos)
        self.bus.subscribe(Topic.FISHING_STATE, self._on_state)
        self._active = True
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
        if self._state != FishingState.FISHING:
            self._emit(False, "no_pos", pos)
            return
        if pos is None:
            # 单帧无漂：保持上一意图，等状态机离开 FISHING 再松
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
