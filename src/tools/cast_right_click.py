"""全局右键按下监听（pynput；回调在监听线程，调用方须切回 UI 线程）。"""

from __future__ import annotations

import threading
from collections.abc import Callable


class CastRightClickListener:
    """监听系统右键按下；不吞事件（不 suppress）。"""

    def __init__(self, on_press: Callable[[], None]) -> None:
        self._on_press = on_press
        self._listener = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            try:
                from pynput.mouse import Button, Listener
            except ImportError:
                return

            def _on_click(x, y, button, pressed):  # noqa: ARG001
                if not pressed:
                    return
                try:
                    if button != Button.right:
                        return
                except Exception:  # noqa: BLE001
                    return
                try:
                    self._on_press()
                except Exception:  # noqa: BLE001
                    pass

            try:
                listener = Listener(on_click=_on_click)
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
