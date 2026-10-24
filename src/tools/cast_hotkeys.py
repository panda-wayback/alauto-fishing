"""全局抛杆开始 / 结束快捷键（pynput；游戏占焦点时仍可用）。"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable

_FKEY = re.compile(r"^F([1-9]|1[0-2])$", re.IGNORECASE)
_LETTER = re.compile(r"^[A-Z]$", re.IGNORECASE)


def normalize_hotkey(raw: str, *, default: str) -> str:
    """规范化为 F8 / A 等形式；非法则回退 default。"""
    s = str(raw or "").strip().upper().replace(" ", "")
    if _FKEY.match(s) or _LETTER.match(s):
        return s
    d = str(default or "F8").strip().upper()
    return d if (_FKEY.match(d) or _LETTER.match(d)) else "F8"


def _to_pynput(key: str) -> str:
    k = normalize_hotkey(key, default="F8")
    if _FKEY.match(k):
        return f"<{k.lower()}>"
    return k.lower()


class CastHotkeyListener:
    """后台全局热键；回调在监听线程触发，调用方须自行切回 UI 线程。"""

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._start_key = "F8"
        self._stop_key = "F9"
        self._listener = None
        self._lock = threading.Lock()

    @property
    def start_key(self) -> str:
        return self._start_key

    @property
    def stop_key(self) -> str:
        return self._stop_key

    def set_keys(self, start: str, stop: str) -> None:
        sk = normalize_hotkey(start, default="F8")
        ek = normalize_hotkey(stop, default="F9")
        if sk == ek:
            ek = "F9" if sk == "F8" else "F8"
        with self._lock:
            same = sk == self._start_key and ek == self._stop_key
            self._start_key = sk
            self._stop_key = ek
            running = self._listener is not None
        if running and not same:
            self.stop()
            self.start()

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            try:
                from pynput import keyboard
            except ImportError:
                return
            mapping = {
                _to_pynput(self._start_key): self._fire_start,
                _to_pynput(self._stop_key): self._fire_stop,
            }
            try:
                listener = keyboard.GlobalHotKeys(mapping)
                listener.start()
            except Exception:  # noqa: BLE001
                return
            self._listener = listener

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # noqa: BLE001
            pass

    def _fire_start(self) -> None:
        try:
            self._on_start()
        except Exception:  # noqa: BLE001
            pass

    def _fire_stop(self) -> None:
        try:
            self._on_stop()
        except Exception:  # noqa: BLE001
            pass
