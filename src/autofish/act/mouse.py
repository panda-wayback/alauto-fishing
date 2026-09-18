"""段5：系统鼠标按下 / 松开（当前光标）。"""

from __future__ import annotations

import sys

try:
    from pynput.mouse import Button, Controller
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 pynput：pip install pynput") from exc


def os_left_down() -> bool | None:
    """读系统左键是否按下；失败返回 None。"""
    if sys.platform == "win32":
        return _win_left_down()

    try:
        from Quartz import (  # type: ignore[import-untyped]
            CGEventSourceButtonState,
            kCGEventSourceStateCombinedSessionState,
            kCGMouseButtonLeft,
        )

        return bool(
            CGEventSourceButtonState(
                kCGEventSourceStateCombinedSessionState,
                kCGMouseButtonLeft,
            )
        )
    except Exception:
        try:
            from AppKit import NSEvent  # type: ignore[import-untyped]

            return bool(NSEvent.pressedMouseButtons() & 1)
        except Exception:
            return None


def _win_left_down() -> bool | None:
    """Windows：GetAsyncKeyState；不依赖「辅助功能」。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        fn = user32.GetAsyncKeyState
        fn.argtypes = (wintypes.INT,)
        fn.restype = wintypes.SHORT
        # SHORT 最高位为 1 ⇒ 当前按下（注意 restype 避免符号截断）
        return bool(fn(0x01) & 0x8000)
    except Exception:
        try:
            import ctypes

            state = int(ctypes.windll.user32.GetAsyncKeyState(0x01))
            return bool(state & 0x8000)
        except Exception:
            return None


class MouseActuator:
    """系统级左键按住 / 松开。"""

    def __init__(self) -> None:
        self._mouse = Controller()
        self._down = False

    @property
    def pressed(self) -> bool:
        return self._down

    def set_holding(self, holding: bool) -> None:
        if holding and not self._down:
            self._mouse.press(Button.left)
            self._down = True
        elif not holding and self._down:
            self._mouse.release(Button.left)
            self._down = False

    def force_release(self) -> None:
        """仅当我们曾按下时才松开；未控鼠则不碰系统。"""
        self.set_holding(False)
