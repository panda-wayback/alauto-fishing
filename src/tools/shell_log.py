"""壳内各页本地日志：写入缓冲 + 独立工具窗展示（不占主控版面）。"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def append_log(logs: deque[str], widget: QPlainTextEdit, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    parts = str(msg).splitlines() or [""]
    block = f"{ts}  {parts[0]}"
    if len(parts) > 1:
        pad = " " * (len(ts) + 2)
        block = block + "\n" + "\n".join(f"{pad}{p}" for p in parts[1:])
    logs.appendleft(block)
    widget.setPlainText("\n".join(logs))
    if widget.verticalScrollBar() is not None:
        widget.verticalScrollBar().setValue(0)


class PageLogPopup:
    """非模态工具窗：主界面只留「日志」按钮，点开可自由拉大。"""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        *,
        object_name: str = "mainLog",
        placeholder: str = "最新在上…",
    ) -> None:
        self.title = title
        self.editor = QPlainTextEdit()
        self.editor.setObjectName(object_name)
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText(placeholder)

        self._win = QDialog(parent)
        self._win.setWindowTitle(title)
        self._win.setModal(False)
        self._win.setWindowFlag(Qt.WindowType.Window, True)
        self._win.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self._win.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self._win.resize(440, 380)
        self._win.setMinimumSize(320, 200)

        root = QVBoxLayout(self._win)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        tip = QLabel("最新在上 · 关闭窗口不丢记录，再点「日志」可打开")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addWidget(self.editor, 1)

    def show(self) -> None:
        self._win.show()
        self._win.raise_()
        self._win.activateWindow()

    def make_button(self, *, text: str = "日志") -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("btnGhost")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(f"打开「{self.title}」工具窗")
        btn.clicked.connect(self.show)
        return btn
