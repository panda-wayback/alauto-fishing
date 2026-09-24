"""壳内各页本地日志（最新在上）。"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtWidgets import QPlainTextEdit


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
