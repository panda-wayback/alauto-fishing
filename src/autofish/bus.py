"""AutofishBus：感知域快照 + 版本作废；推送委托 EventBus。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from common.pubsub import EventBus
from autofish.detect.bobber import BobberHit
from autofish.locate.roi import Roi
from autofish.topics import (
    ActionIntentEvent,
    FishingState,
    FishingStateEvent,
    FrameEvent,
    PosEvent,
    RoiEvent,
    Topic,
)


@dataclass
class AutofishSnapshot:
    roi: Roi | None = None
    roi_version: int = 0
    roi_score: float = 0.0
    roi_source: str = ""
    frame: np.ndarray | None = None
    frame_ts: float = 0.0
    pos: float | None = None
    hit: BobberHit | None = None
    pos_ts: float = 0.0
    fishing_state: FishingState = FishingState.IDLE
    fishing_detail: str = ""
    state_ts: float = 0.0
    holding: bool | None = None
    intent_reason: str = ""
    intent_ts: float = 0.0


class AutofishBus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events = EventBus()
        self._snap = AutofishSnapshot()

    def subscribe(self, topic: Topic, callback: Callable) -> None:
        self._events.subscribe(topic, callback)

    def unsubscribe(self, topic: Topic, callback: Callable) -> None:
        self._events.unsubscribe(topic, callback)

    def snapshot(self) -> AutofishSnapshot:
        with self._lock:
            s = self._snap
            return replace(s, frame=None if s.frame is None else s.frame.copy())

    def current_roi(self) -> tuple[Roi | None, int]:
        with self._lock:
            return self._snap.roi, self._snap.roi_version

    def publish_roi(self, event: RoiEvent) -> None:
        with self._lock:
            # 已有手框时，禁止 green 覆盖
            if (
                event.roi is not None
                and event.source == "green"
                and self._snap.roi is not None
                and self._snap.roi_source == "manual"
            ):
                return
            self._snap.roi = event.roi
            self._snap.roi_version = event.version
            self._snap.roi_score = event.score
            self._snap.roi_source = event.source
            self._snap.frame = None
            self._snap.frame_ts = 0.0
        self._events.publish(Topic.ROI, event)

    def publish_frame(self, event: FrameEvent) -> None:
        with self._lock:
            if event.roi_version != self._snap.roi_version:
                return
            self._snap.frame = event.frame
            self._snap.frame_ts = event.ts
        self._events.publish(Topic.FRAME, event)

    def publish_pos(self, event: PosEvent) -> None:
        with self._lock:
            if event.roi_version != self._snap.roi_version:
                return
            self._snap.pos = event.pos
            self._snap.hit = event.hit
            self._snap.pos_ts = event.ts
        self._events.publish(Topic.POS, event)

    def publish_fishing_state(self, event: FishingStateEvent) -> None:
        with self._lock:
            if (
                event.state == self._snap.fishing_state
                and event.detail == self._snap.fishing_detail
            ):
                return
            self._snap.fishing_state = event.state
            self._snap.fishing_detail = event.detail
            self._snap.state_ts = event.ts
        self._events.publish(Topic.FISHING_STATE, event)

    def publish_action_intent(self, event: ActionIntentEvent) -> None:
        with self._lock:
            self._snap.holding = event.holding
            self._snap.intent_reason = event.reason
            self._snap.intent_ts = event.ts
        self._events.publish(Topic.ACTION_INTENT, event)

    def clear_roi(self, source: str = "clear") -> None:
        with self._lock:
            version = self._snap.roi_version + 1
        self.publish_roi(
            RoiEvent(roi=None, version=version, ts=time.time(), source=source)
        )
