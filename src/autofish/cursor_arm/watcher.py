"""后台低频认光标外形：enabled 时循环读取系统光标位图并更新 armed / shape。"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from autofish.cursor_arm.detect import classify_cursor_shape
from autofish.cursor_arm.grab import grab_system_cursor


class CursorArmWatcher:
    """系统光标外形观察者；构造不起线程。"""

    def __init__(
        self,
        *,
        interval_s: float = 0.3,
        size: int = 100,
        on_armed_changed: Callable[[bool], None] | None = None,
        on_frame: Callable[[np.ndarray, bool, str], None] | None = None,
    ) -> None:
        self._interval_s = max(0.05, float(interval_s))
        self._size = max(16, int(size))  # 保留兼容；不再用于截屏边长
        self._on_armed_changed = on_armed_changed
        self._on_frame = on_frame
        self._enabled = False
        self._armed = False
        self._shape = "other"
        self._last_frame: np.ndarray | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    @property
    def shape(self) -> str:
        """当前外形：bobber / hook / other。"""
        with self._lock:
            return self._shape

    @property
    def last_frame(self) -> np.ndarray | None:
        """最近一次成功读到的光标图（RGB 或 RGBA）副本。"""
        with self._lock:
            if self._last_frame is None:
                return None
            return self._last_frame.copy()

    def is_running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        with self._lock:
            self._enabled = enabled
            if not enabled and self._armed:
                self._armed = False
                self._shape = "other"
                cb = self._on_armed_changed
            else:
                cb = None
            if not enabled:
                self._last_frame = None
                self._shape = "other"
        if cb is not None:
            try:
                cb(False)
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="CursorArmWatcher", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=max(0.0, float(timeout)))
        with self._lock:
            self._thread = None
            was = self._armed
            self._armed = False
            self._shape = "other"
            self._enabled = False
            self._last_frame = None
            cb = self._on_armed_changed if was else None
        if cb is not None:
            try:
                cb(False)
            except Exception:  # noqa: BLE001
                pass

    def _set_armed(self, armed: bool) -> None:
        armed = bool(armed)
        with self._lock:
            if self._armed == armed:
                return
            self._armed = armed
            cb = self._on_armed_changed
        if cb is not None:
            try:
                cb(armed)
            except Exception:  # noqa: BLE001
                pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                enabled = self._enabled
            if enabled:
                try:
                    frame = grab_system_cursor()
                    if frame is not None:
                        shape = classify_cursor_shape(frame)
                        armed = shape == "bobber"
                        with self._lock:
                            self._last_frame = np.asarray(frame).copy()
                            self._shape = shape
                            frame_cb = self._on_frame
                        self._set_armed(armed)
                        if frame_cb is not None:
                            try:
                                frame_cb(frame, armed, shape)
                            except Exception:  # noqa: BLE001
                                pass
                except Exception:  # noqa: BLE001
                    pass
            if self._stop.wait(self._interval_s):
                break
