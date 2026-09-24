"""段4：DecideWorker — 订 Pos → 发 ActionIntent。"""

from __future__ import annotations

import time

from autofish.bus import AutofishBus
from autofish.decide.policy import ThresholdPosPolicy
from autofish.topics import (
    ActionIntentEvent,
    CastSessionEvent,
    CastSessionState,
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
        press_lo: float = 70.6,
        press_hi: float = 74.4,
        release_lo: float = 76.6,
        release_hi: float = 79.2,
    ) -> None:
        self.bus = bus
        self._policy = ThresholdPosPolicy(
            press_lo=press_lo,
            press_hi=press_hi,
            release_lo=release_lo,
            release_hi=release_hi,
        )
        self._state = FishingState.IDLE
        self._cast = CastSessionState.DISABLED
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
        self._policy.reset()
        self._last_holding = None
        self.bus.subscribe(Topic.POS, self._on_pos)
        self.bus.subscribe(Topic.FISHING_STATE, self._on_state)
        self.bus.subscribe(Topic.CAST_SESSION, self._on_cast)
        self._active = True
        self._sync_from_snapshot()

    def stop(self) -> None:
        if not self._active:
            return
        self.bus.unsubscribe(Topic.POS, self._on_pos)
        self.bus.unsubscribe(Topic.FISHING_STATE, self._on_state)
        self.bus.unsubscribe(Topic.CAST_SESSION, self._on_cast)
        self._active = False
        self._emit(False, "decide_stop", None)

    def _may_pull(self) -> bool:
        """A 关：跟鱼漂 FSM；A 开：仅会话 FISHING。"""
        if self._cast == CastSessionState.DISABLED:
            return self._state == FishingState.FISHING
        return self._cast == CastSessionState.FISHING

    def _sync_from_snapshot(self) -> None:
        snap = self.bus.snapshot()
        self._state = snap.fishing_state
        self._cast = snap.cast_session
        self._apply_pos(snap.pos)

    def _on_state(self, event: FishingStateEvent) -> None:
        self._state = event.state
        if not self._may_pull():
            self._policy.reset()
            self._emit(False, f"state_{event.state.value}", None)
            return
        self._apply_pos(self.bus.snapshot().pos)

    def _on_cast(self, event: CastSessionEvent) -> None:
        self._cast = event.state
        if not self._may_pull():
            self._policy.reset()
            self._emit(False, f"cast_{event.state.value}", None)
            return
        self._apply_pos(self.bus.snapshot().pos)

    def _on_pos(self, event: PosEvent) -> None:
        self._apply_pos(event.pos)

    def _apply_pos(self, pos: float | None) -> None:
        if not self._may_pull():
            self._emit(False, "not_pulling", pos)
            return
        if pos is None:
            # 单帧无漂：保持上一意图，等离开可拉漂条件再松
            return
        holding, reason = self._policy.decide(pos)
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
