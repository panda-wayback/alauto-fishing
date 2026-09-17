"""段3：识别工人。"""

from __future__ import annotations

import threading
import time
import traceback

from autofish.bus import AutofishBus
from autofish.detect.api import detect
from autofish.topics import FrameEvent, PosEvent, Topic
from autofish.worker_base import WorkerBase


class DetectorWorker(WorkerBase):
    """订 Frame → 当前识别器 → Pos；不改 ROI。只认最新帧，历史抛弃。"""

    def __init__(self, bus: AutofishBus) -> None:
        super().__init__(bus, "autofish-detector")
        self._last_seq = -1
        self._pending: FrameEvent | None = None
        self._cond = threading.Condition()

    def start(self) -> None:
        # 重启后必须清序号，否则 capture 若重置 seq 会永久跳过所有帧
        self._last_seq = -1
        with self._cond:
            self._pending = None
        self.bus.subscribe(Topic.FRAME, self._on_frame)
        super().start()

    def stop(self, timeout: float = 2.0) -> None:
        self.bus.unsubscribe(Topic.FRAME, self._on_frame)
        with self._cond:
            self._pending = None
            self._cond.notify_all()
        super().stop(timeout=timeout)

    def _on_frame(self, event: FrameEvent) -> None:
        with self._cond:
            self._pending = event
            self._cond.notify()

    def _take_latest(self) -> FrameEvent | None:
        with self._cond:
            while self._pending is None and not self._stop.is_set():
                self._cond.wait(timeout=0.2)
            event = self._pending
            self._pending = None
            return event

    def _superseded(self, seq: int) -> bool:
        with self._cond:
            return self._pending is not None and self._pending.seq > seq

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._take_latest()
                if event is None:
                    continue
                if event.seq <= self._last_seq:
                    continue
                if self._superseded(event.seq):
                    continue
                try:
                    raw = detect(event.frame)
                except Exception:  # noqa: BLE001
                    # 单帧异常不得杀死识别线程（否则监控仍动、Pos 永久停）
                    traceback.print_exc()
                    raw = None
                self._last_seq = event.seq
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
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                self._stop.wait(0.05)
