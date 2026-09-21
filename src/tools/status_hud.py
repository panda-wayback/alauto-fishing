"""主窗紧凑态面板：阶段灯（嵌入同一窗口，非独立窗）。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from tools.shell_theme import (
    ACCENT,
    ACCENT_ON,
    BG,
    BORDER_SOFT,
    DANGER,
    SUCCESS,
    SURFACE,
    TEXT_FAINT,
    TEXT_MUTED,
    WARN,
)

_PHASE_STYLE: dict[str, tuple[str, str]] = {
    "idle": ("待机", TEXT_FAINT),
    "listen": ("听声中", TEXT_MUTED),
    "heard": ("听到声音", ACCENT),
    "wait_bobber": ("等漂", WARN),
    "game_start": ("开始游戏", SUCCESS),
    "pull": ("拉漂", ACCENT),
    "release": ("松漂", SUCCESS),
    "game_end": ("结束游戏", DANGER),
}

_FLASH_MS = 1200


class StatusHudPanel(QWidget):
    """紧凑态内容：阶段 + 上次 + 切回主界面。"""

    expand_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("hudPanel")
        self.setStyleSheet(
            f"QWidget#hudPanel {{ background: {BG}; border: none; }}"
        )

        inner = QVBoxLayout(self)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)

        self.lbl_phase = QLabel("待机")
        self.lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phase.setStyleSheet(
            f"font-size:22px; font-weight:700; color:{TEXT_FAINT}; background:transparent;"
        )
        inner.addWidget(self.lbl_phase)

        self.lbl_last = QLabel("上次：—")
        self.lbl_last.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_last.setStyleSheet(
            f"font-size:11px; color:{TEXT_FAINT}; background:transparent;"
        )
        inner.addWidget(self.lbl_last)

        self.btn_expand = QPushButton("主界面")
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setToolTip("切回完整调试界面")
        self.btn_expand.setStyleSheet(
            f"""
            QPushButton {{
                background: {ACCENT};
                color: {ACCENT_ON};
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #4ac9b0; }}
            """
        )
        self.btn_expand.clicked.connect(self.expand_requested.emit)
        inner.addWidget(self.btn_expand)

        self._steady_key = "idle"
        self._flash_until = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._apply_phase("idle")

    def set_steady(self, key: str) -> None:
        if key not in _PHASE_STYLE:
            key = "idle"
        self._steady_key = key
        if time.time() < self._flash_until:
            return
        self._apply_phase(key)

    def flash(self, key: str) -> None:
        if key not in _PHASE_STYLE:
            return
        label, _ = _PHASE_STYLE[key]
        self.note_last(label)
        self._flash_until = time.time() + _FLASH_MS / 1000.0
        self._apply_phase(key)
        self._flash_timer.start(_FLASH_MS)

    def _end_flash(self) -> None:
        self._flash_until = 0.0
        self._apply_phase(self._steady_key)

    def note_last(self, label: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.lbl_last.setText(f"上次：{label} · {ts}")

    def _apply_phase(self, key: str) -> None:
        label, color = _PHASE_STYLE.get(key, _PHASE_STYLE["idle"])
        self.lbl_phase.setText(label)
        self.lbl_phase.setStyleSheet(
            f"font-size:22px; font-weight:700; color:{color}; background:transparent;"
        )
        if key in ("heard", "game_start", "game_end"):
            self.setStyleSheet(
                f"QWidget#hudPanel {{ background: {SURFACE}; "
                f"border: 1px solid {color}; border-radius: 8px; }}"
            )
        else:
            self.setStyleSheet(
                f"QWidget#hudPanel {{ background: {BG}; "
                f"border: 1px solid {BORDER_SOFT}; border-radius: 8px; }}"
            )
