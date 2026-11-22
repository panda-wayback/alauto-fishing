"""段2：mss 截图工人（常驻服务：失败重启会话，连续重启失败才暂停截屏）。"""

from __future__ import annotations

import sys
import time

from autofish.events.bus import AutofishBus
from autofish.capture.screen import close_session, grab_roi, warmup
from autofish.events.topics import FrameEvent
from autofish.events.worker_base import WorkerBase

# 低配 Windows 上 30～45fps 易把 GDI 打满，瞬时 BitBlt 失败变多
_DEFAULT_FPS = 20.0 if sys.platform == "win32" else 30.0
_FAIL_BACKOFF_STEP_S = 0.05
_FAIL_BACKOFF_MAX_S = 0.5
# 连续「重启会话」失败这么多次 → 暂停截屏（线程仍在），隔一段时间再拉起
_MAX_RESTART_FAILS = 5
_SUSPEND_RETRY_S = 2.0


def default_capture_fps() -> float:
    """平台默认截屏频率；Windows 偏低以降低弱机 GDI 压力。"""
    return _DEFAULT_FPS


class CaptureWorker(WorkerBase):
    """常驻截屏服务：有 ROI 就出帧；单次失败重启 mss 会话；连续重启失败才暂停执行。"""

    def __init__(self, bus: AutofishBus, *, fps: float | None = None) -> None:
        super().__init__(bus, "autofish-capture")
        rate = float(default_capture_fps() if fps is None else fps)
        self._dt = 1.0 / max(1.0, rate)
        self._seq = 0
        self._restart_fails = 0
        self._grab_fails = 0
        self._suspended = False
        self._last_err_log = 0.0
        self._last_error: str = ""

    @property
    def suspended(self) -> bool:
        """连续重启失败后暂停截屏（线程仍存活）。"""
        return self._suspended

    @property
    def restart_fails(self) -> int:
        return self._restart_fails

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self) -> None:
        self._seq = 0
        self._restart_fails = 0
        self._grab_fails = 0
        self._suspended = False
        self._last_error = ""
        super().start()

    def _log(self, msg: str) -> None:
        now = time.perf_counter()
        if now - self._last_err_log < 1.0:
            return
        self._last_err_log = now
        print(f"[capture] {msg}", flush=True)

    def _restart_session(self) -> bool:
        """关掉坏会话并预热新会话；成功 True。"""
        close_session()
        try:
            warmup()
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            close_session()
            return False

    def _backoff_s(self) -> float:
        n = max(1, self._grab_fails)
        return max(
            self._dt,
            min(_FAIL_BACKOFF_MAX_S, _FAIL_BACKOFF_STEP_S * n),
        )

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                t0 = time.perf_counter()
                roi, version = self.bus.current_roi()
                if roi is None or version <= 0:
                    elapsed = time.perf_counter() - t0
                    self._stop.wait(max(0.0, self._dt - elapsed))
                    continue

                # 连续重启失败：暂停执行截屏，隔一会再尝试拉起服务
                if self._suspended:
                    if self._restart_session():
                        self._suspended = False
                        self._restart_fails = 0
                        self._grab_fails = 0
                        self._log("session recovered · resume")
                    else:
                        self._restart_fails += 1
                        self._log(
                            f"suspend retry failed · restart {self._restart_fails}"
                        )
                        self._stop.wait(_SUSPEND_RETRY_S)
                    continue

                try:
                    frame = grab_roi(roi)
                except Exception as exc:  # noqa: BLE001
                    self._last_error = str(exc)
                    self._grab_fails += 1
                    self._log(f"grab failed · {exc} · restarting session")
                    # 失败 → 必须重启会话（常驻服务）
                    if self._restart_session():
                        # 重启成功：继续跑，短退避后再截；不计入「重启失败」
                        self._restart_fails = 0
                        self._stop.wait(self._backoff_s())
                    else:
                        self._restart_fails += 1
                        self._log(
                            f"session restart failed · {self._restart_fails}/"
                            f"{_MAX_RESTART_FAILS}"
                        )
                        if self._restart_fails >= _MAX_RESTART_FAILS:
                            self._suspended = True
                            self._log(
                                f"suspend capture · {_MAX_RESTART_FAILS} restart fails"
                            )
                            self._stop.wait(_SUSPEND_RETRY_S)
                        else:
                            self._stop.wait(self._backoff_s())
                    continue

                # 出帧成功：服务健康
                self._restart_fails = 0
                self._grab_fails = 0
                self._suspended = False
                self._last_error = ""
                self._seq += 1
                self.bus.publish_frame(
                    FrameEvent(
                        frame=frame,
                        roi_version=version,
                        ts=time.perf_counter(),
                        seq=self._seq,
                    )
                )
                elapsed = time.perf_counter() - t0
                self._stop.wait(max(0.0, self._dt - elapsed))
        finally:
            close_session()
