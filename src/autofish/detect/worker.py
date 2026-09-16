"""段3：识别工人。"""

from __future__ import annotations

import threading
import time

from autofish.bus import AutofishBus
from autofish.detect.bobber import find_bobber
from autofish.detect.hsv_calib import ZoneHsv, load_zone_hsv
from autofish.detect.smooth import PosSmoother
from autofish.topics import FrameEvent, PosEvent, Topic
from autofish.worker_base import WorkerBase


class DetectorWorker(WorkerBase):
    """消费帧 → 色块读数 → 发布 Pos。"""

    def __init__(self, bus: AutofishBus, *, zone: ZoneHsv | None = None) -> None:
        super().__init__(bus, "autofish-detector")
        self._zone = zone or load_zone_hsv()
        self._smoother = PosSmoother(window=7, hold_lost=12)
        self._last_frame_ts = 0.0
        self._pending: FrameEvent | None = None
        self._cond = threading.Condition()
        bus.subscribe(Topic.FRAME, self._on_frame)

    def set_zone(self, zone: ZoneHsv) -> None:
        self._zone = zone
        self._smoother.reset()

    def stop(self, timeout: float = 2.0) -> None:
        self.bus.unsubscribe(Topic.FRAME, self._on_frame)
        with self._cond:
            self._cond.notify_all()
        super().stop(timeout=timeout)

    def _on_frame(self, event: FrameEvent) -> None:
        with self._cond:
            self._pending = event
            self._cond.notify()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait(timeout=0.05)
                event = self._pending
                self._pending = None
            if event is None:
                continue
            if event.ts <= self._last_frame_ts:
                continue
            self._last_frame_ts = event.ts
            raw = find_bobber(
                event.frame, lower=self._zone.lower, upper=self._zone.upper
            )
            hit = self._smoother.push(raw)
            self.bus.publish_pos(
                PosEvent(
                    pos=None if hit is None else hit.pos,
                    hit=hit,
                    roi_version=event.roi_version,
                    frame_ts=event.ts,
                    ts=time.time(),
                )
            )
