"""段2：mss 截图工人。"""

from __future__ import annotations

import time

from autofish.bus import AutofishBus
from autofish.capture.screen import grab_roi
from autofish.topics import FrameEvent
from autofish.worker_base import WorkerBase


class CaptureWorker(WorkerBase):
    """按总线 ROI 持续截帧；无 ROI 则空转等待。"""

    def __init__(self, bus: AutofishBus, *, fps: float = 30.0) -> None:
        super().__init__(bus, "autofish-capture")
        self._dt = 1.0 / max(1.0, fps)
        self._seq = 0

    def start(self) -> None:
        self._seq = 0
        super().start()

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            roi, version = self.bus.current_roi()
            if roi is not None and version > 0:
                try:
                    frame = grab_roi(roi)
                    self._seq += 1
                    self.bus.publish_frame(
                        FrameEvent(
                            frame=frame,
                            roi_version=version,
                            ts=time.perf_counter(),
                            seq=self._seq,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    # 避免刷屏：每秒最多记一次
                    now = time.perf_counter()
                    last = getattr(self, "_last_err_log", 0.0)
                    if now - last >= 1.0:
                        self._last_err_log = now
                        print(f"[capture] grab_roi failed: {exc}", flush=True)
                    self._stop.wait(self._dt)
                    continue
            elapsed = time.perf_counter() - t0
            self._stop.wait(max(0.0, self._dt - elapsed))
