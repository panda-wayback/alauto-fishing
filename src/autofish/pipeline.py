"""感知流水线：总线 + 分段启停（监控 / 策略 / 操作）。"""

from __future__ import annotations

import time

from autofish.act.worker import ActWorker
from autofish.bus import AutofishBus, AutofishSnapshot
from autofish.capture import warmup as warmup_capture
from autofish.capture.worker import CaptureWorker
from autofish.decide.worker import DecideWorker
from autofish.detect.worker import DetectorWorker
from autofish.fishing_fsm import FishingStateMachine
from autofish.locate import Roi
from autofish.locate.worker import LocatorWorker
from autofish.topics import RoiEvent, Topic


class AutofishPipeline:
    """
    各段经总线交接；监控 / 策略 / 操作可独立 start/stop。
    操作默认不启动。
    """

    def __init__(
        self,
        *,
        locate_interval_s: float = 1.5,
        capture_fps: float = 45.0,
        auto_locate: bool = False,
    ) -> None:
        self.bus = AutofishBus()
        self.fsm = FishingStateMachine(self.bus)
        self.locator = LocatorWorker(self.bus, interval_s=locate_interval_s)
        self.capture = CaptureWorker(self.bus, fps=capture_fps)
        self.detector = DetectorWorker(self.bus)
        self.decide = DecideWorker(self.bus)
        self.act = ActWorker(self.bus)
        self._auto_locate = auto_locate
        self._roi_version = 0
        self._monitor_on = False
        self._decide_on = False
        self._act_on = False
        self._warmed = False

    @property
    def monitor_on(self) -> bool:
        return self._monitor_on

    @property
    def decide_on(self) -> bool:
        return self._decide_on

    @property
    def act_on(self) -> bool:
        return self._act_on

    def subscribe(self, topic: Topic, callback) -> None:
        self.bus.subscribe(topic, callback)

    def unsubscribe(self, topic: Topic, callback) -> None:
        self.bus.unsubscribe(topic, callback)

    def snapshot(self) -> AutofishSnapshot:
        return self.bus.snapshot()

    def set_roi_manual(self, roi: Roi) -> None:
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
        self.locator._version = self._roi_version

    def clear_roi(self) -> None:
        self.bus.clear_roi("manual")
        self._roi_version = self.bus.snapshot().roi_version
        self.locator._version = self._roi_version

    def set_decide_thresholds(self, low: float, high: float) -> None:
        self.decide.set_thresholds(low, high)

    def locate_now(self) -> RoiEvent | None:
        return self.locator.locate_once()

    def _warmup(self) -> None:
        if self._warmed:
            return
        try:
            warmup_capture()
        except Exception:  # noqa: BLE001
            pass
        self._warmed = True

    def start_monitor(self) -> None:
        """Capture + Detect（+ 可选 Locator）。"""
        if self._monitor_on:
            return
        self._warmup()
        self.detector.start()
        self.capture.start()
        if self._auto_locate:
            self.locator.start()
        self._monitor_on = True

    def stop_monitor(self) -> None:
        if not self._monitor_on:
            return
        self.locator.stop()
        self.capture.stop()
        self.detector.stop()
        self._monitor_on = False

    def start_decide(self) -> None:
        if self._decide_on:
            return
        self.decide.start()
        self._decide_on = True

    def stop_decide(self) -> None:
        if not self._decide_on:
            return
        self.decide.stop()
        self._decide_on = False

    def start_act(self) -> None:
        if self._act_on:
            return
        self.act.start()
        self._act_on = True

    def stop_act(self) -> None:
        if not self._act_on:
            return
        self.act.stop()
        self._act_on = False

    def start(self) -> None:
        """兼容：开监控+策略；不开操作。"""
        self.start_monitor()
        self.start_decide()

    def stop(self) -> None:
        self.stop_act()
        self.stop_decide()
        self.stop_monitor()
