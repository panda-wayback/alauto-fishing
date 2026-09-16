"""钓鱼状态机：订阅读数/ROI，发布 FishingState。"""

from __future__ import annotations

import time

from autofish.bus import AutofishBus
from autofish.topics import FishingState, FishingStateEvent, PosEvent, RoiEvent, Topic


class FishingStateMachine:
    """
    IDLE → FISHING：有 ROI 且读数有效
    FISHING → LOST：连续丢读数
    LOST → FISHING：读数恢复
    LOST/FISHING → IDLE：ROI 清空或长时间丢失
    """

    def __init__(
        self,
        bus: AutofishBus,
        *,
        lost_after: int = 15,
        idle_after: int = 60,
    ) -> None:
        self._bus = bus
        self._lost_after = lost_after
        self._idle_after = idle_after
        self._miss = 0
        self._state = FishingState.IDLE
        self._has_roi = False
        bus.subscribe(Topic.ROI, self._on_roi)
        bus.subscribe(Topic.POS, self._on_pos)

    def _set(self, state: FishingState, detail: str = "") -> None:
        if state == self._state and not detail:
            return
        self._state = state
        self._bus.publish_fishing_state(
            FishingStateEvent(state=state, ts=time.time(), detail=detail)
        )

    def _on_roi(self, event: RoiEvent) -> None:
        self._has_roi = event.roi is not None
        if not self._has_roi:
            self._miss = 0
            self._set(FishingState.IDLE, "roi_cleared")

    def _on_pos(self, event: PosEvent) -> None:
        if not self._has_roi:
            self._set(FishingState.IDLE, "no_roi")
            return
        if event.pos is not None:
            self._miss = 0
            self._set(FishingState.FISHING, "pos_ok")
            return
        self._miss += 1
        if self._state == FishingState.FISHING and self._miss >= self._lost_after:
            self._set(FishingState.LOST, "pos_miss")
        elif self._state == FishingState.LOST and self._miss >= self._idle_after:
            self._set(FishingState.IDLE, "pos_gone")
        elif self._state == FishingState.IDLE and self._miss < self._lost_after:
            # 仍无有效读数，保持 IDLE
            pass
