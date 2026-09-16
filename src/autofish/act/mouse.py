"""段5：系统鼠标按下 / 松开（当前光标）。"""

from __future__ import annotations

try:
    from pynput.mouse import Button, Controller
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 pynput：pip install pynput") from exc


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
        self.set_holding(False)
