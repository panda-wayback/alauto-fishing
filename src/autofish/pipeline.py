"""感知流水线：总线 + 分段启停（监控 / 策略 / 操作）。"""

from __future__ import annotations

import time

from autofish.act.worker import ActWorker
from autofish.auto_cast import AutoCastWorker
from autofish.events.bus import AutofishBus, AutofishSnapshot
from autofish.capture import warmup as warmup_capture
from autofish.capture.worker import CaptureWorker
from autofish.decide.worker import DecideWorker
from autofish.detect.worker import DetectorWorker
from autofish.fishing_fsm import FishingStateMachine
from autofish.locate import Roi
from autofish.events.topics import RoiEvent, Topic


class AutofishPipeline:
    """
    各段经总线交接；监控 / 策略 / 操作可独立 start/stop。
    """

    def __init__(
        self,
        *,
        capture_fps: float = 45.0,
        cast_wait_lo_s: float = 3.0,
        cast_wait_hi_s: float = 3.0,
        cast_full_charge_s: float = 1.0,
    ) -> None:
        self.bus = AutofishBus()
        self.fsm = FishingStateMachine(self.bus)
        self.capture = CaptureWorker(self.bus, fps=capture_fps)
        self.detector = DetectorWorker(self.bus)
        self.decide = DecideWorker(self.bus)
        self.act = ActWorker(self.bus)
        self.auto_cast = AutoCastWorker(
            self.bus,
            wait_lo_s=cast_wait_lo_s,
            wait_hi_s=cast_wait_hi_s,
            full_charge_s=cast_full_charge_s,
        )
        self._roi_version = 0
        self._monitor_on = False
        self._decide_on = False
        self._act_on = False
        self._auto_cast_on = False
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

    @property
    def auto_cast_on(self) -> bool:
        return self._auto_cast_on

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

    def clear_roi(self) -> None:
        self.bus.clear_roi("manual")
        self._roi_version = self.bus.snapshot().roi_version

    def set_decide_ranges(
        self,
        press_lo: float,
        press_hi: float,
        release_lo: float,
        release_hi: float,
    ) -> None:
        self.decide.set_ranges(press_lo, press_hi, release_lo, release_hi)

    def _warmup(self) -> None:
        if self._warmed:
            return
        try:
            warmup_capture()
        except Exception:  # noqa: BLE001
            pass
        self._warmed = True

    def start_monitor(self) -> None:
        """Capture + Detect。"""
        if self._monitor_on:
            return
        self._warmup()
        self.bus.reset_pos_seq()
        self.detector.start()
        self.capture.start()
        self._monitor_on = True

    def stop_monitor(self) -> None:
        if not self._monitor_on:
            return
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

    def start_auto_cast(self) -> None:
        """启自动抛杆工人线程（默认空闲；开抛用 start_cast_batch）。"""
        if self._auto_cast_on:
            return
        self.auto_cast.start()
        self._auto_cast_on = True

    def stop_auto_cast(self) -> None:
        if not self._auto_cast_on:
            return
        self.auto_cast.cancel_batch()
        self.auto_cast.stop()
        self._auto_cast_on = False

    def start_cast_batch(self, count: int) -> bool:
        """开始一轮有限次数抛杆（转交 AutoCastWorker.start_batch）。"""
        return self.auto_cast.start_batch(count)

    def cancel_cast_batch(self) -> None:
        """立刻结束当前抛杆任务（转交 AutoCastWorker.cancel_batch）。"""
        self.auto_cast.cancel_batch()

    def set_cast_wait_range(self, lo_s: float, hi_s: float) -> None:
        self.auto_cast.set_wait_range(lo_s, hi_s)

    def set_cast_full_charge_s(self, seconds: float) -> None:
        self.auto_cast.set_full_charge_s(seconds)

    def stop(self) -> None:
        self.stop_auto_cast()
        self.stop_act()
        self.stop_decide()
        self.stop_monitor()
