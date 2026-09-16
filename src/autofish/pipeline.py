"""感知流水线：总线 + 状态机 + 三生产者启停。"""

from __future__ import annotations

import time
from pathlib import Path

from autofish.bus import AutofishBus, AutofishSnapshot
from autofish.capture import warmup as warmup_capture
from autofish.capture.worker import CaptureWorker
from autofish.detect.worker import DetectorWorker
from autofish.fishing_fsm import FishingStateMachine
from autofish.locate import DEFAULT_BAR_TEMPLATE, Roi
from autofish.locate.worker import LocatorWorker
from autofish.topics import RoiEvent, Topic


class AutofishPipeline:
    """
    Locator（找条）→ Capture（截图）→ Detector（读数）
    FishingStateMachine 订阅读数；外部 subscribe 总线主题。
    """

    def __init__(
        self,
        *,
        template_path: Path = DEFAULT_BAR_TEMPLATE,
        locate_interval_s: float = 1.5,
        capture_fps: float = 30.0,
        auto_locate: bool = True,
    ) -> None:
        self.bus = AutofishBus()
        self.fsm = FishingStateMachine(self.bus)
        self.locator = LocatorWorker(
            self.bus,
            template_path=template_path,
            interval_s=locate_interval_s,
        )
        self.capture = CaptureWorker(self.bus, fps=capture_fps)
        self.detector = DetectorWorker(self.bus)
        self._auto_locate = auto_locate
        self._roi_version = 0

    def subscribe(self, topic: Topic, callback) -> None:
        self.bus.subscribe(topic, callback)

    def unsubscribe(self, topic: Topic, callback) -> None:
        self.bus.unsubscribe(topic, callback)

    def snapshot(self) -> AutofishSnapshot:
        return self.bus.snapshot()

    def set_roi_manual(self, roi: Roi) -> None:
        """手动框选结果灌入总线（与模板找条并存）。"""
        self._roi_version += 1
        self.bus.publish_roi(
            RoiEvent(
                roi=roi,
                version=self._roi_version,
                ts=time.time(),
                source="manual",
                score=1.0,
            )
        )
        # 与 Locator 版本对齐，避免模板覆盖时 version 回退
        self.locator._version = self._roi_version

    def clear_roi(self) -> None:
        self.bus.clear_roi("manual")
        self._roi_version = self.bus.snapshot().roi_version
        self.locator._version = self._roi_version

    def locate_now(self) -> RoiEvent | None:
        return self.locator.locate_once()

    def start(self) -> None:
        try:
            warmup_capture()
        except Exception:  # noqa: BLE001
            pass
        self.detector.start()
        self.capture.start()
        if self._auto_locate:
            self.locator.start()

    def stop(self) -> None:
        self.locator.stop()
        self.capture.stop()
        self.detector.stop()
