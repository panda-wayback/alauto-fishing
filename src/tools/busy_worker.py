"""后台跑可调用对象，避免卡死 UI。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal


class FnWorker(QThread):
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, fn: Callable[[], object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.ok.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.err.emit(str(exc))
