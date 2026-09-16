"""段3：识别工人。"""

from __future__ import annotations

import threading
import time

from autofish.bus import AutofishBus
from autofish.detect.bobber import find_bobber
from autofish.topics import FrameEvent, PosEvent, Topic
from autofish.worker_base import WorkerBase


class DetectorWorker(WorkerBase):
    """
    消费 Frame → 发 Pos（绿端+5% 内找白）。
    latest-wins；Pos 携带被分析的那一帧，保证 UI 读数与画面同频。
    """

    def __init__(self, bus: AutofishBus) -> None:
        super().__init__(bus, "autofish-detector")
        self._last_seq = -1
        self._pending: FrameEvent | None = None
        self._cond = threading.Condition()
        bus.subscribe(Topic.FRAME, self._on_frame)

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
                while self._pending is None and not self._stop.is_set():
                    self._cond.wait(timeout=0.2)
                event = self._pending
                self._pending = None
            if event is None:
                continue
            if event.seq <= self._last_seq:
                continue
            self._last_seq = event.seq
            raw = find_bobber(event.frame)
            self.bus.publish_pos(
                PosEvent(
                    pos=None if raw is None else raw.pos,
                    hit=raw,
                    roi_version=event.roi_version,
                    frame_ts=event.ts,
                    ts=time.time(),
                    frame_seq=event.seq,
                    frame=event.frame,
                )
            )
