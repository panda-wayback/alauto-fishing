"""主窗紧凑态：无边框小仪表盘（窗体整体半透明，可调）。"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tools.shell_theme import (
    ACCENT,
    ACCENT_ON,
    BG,
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
    "heard": ("听到", ACCENT),
    "wait_bobber": ("等漂", WARN),
    "game_start": ("开局", SUCCESS),
    "pull": ("拉", ACCENT),
    "release": ("松", SUCCESS),
    "game_end": ("结束", DANGER),
    "cast_wait": ("抛·等", TEXT_MUTED),
    "cast_aim": ("瞄准", WARN),
    "cast_charge": ("蓄力", ACCENT),
    "cast_start": ("开始抛竿", SUCCESS),
    "cast_end": ("结束抛竿", WARN),
}

_CHROME_FLASH = ("heard", "game_start", "game_end", "cast_start", "cast_end")

_FLASH_MS = 1200


class StatusHudPanel(QWidget):
    """紧凑态：左 POS/抛杆/鼠标，右竖排阶段；透明度 + 切回。"""

    expand_requested = Signal()
    opacity_changed = Signal(float)  # 0.45～1.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("hudPanel")
        self._drag_origin: QPoint | None = None
        self._apply_panel_chrome()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(3)

        # 左：POS/抛杆/鼠标；右：阶段竖排小字（不占顶行）
        body = QHBoxLayout()
        body.setSpacing(6)
        metrics = QVBoxLayout()
        metrics.setSpacing(2)
        metrics.setContentsMargins(0, 0, 0, 0)
        self.lbl_pos = self._row(metrics, "POS")
        self.lbl_cast = self._row(metrics, "抛竿")
        self.lbl_cast_badge = QLabel("抛竿中")
        self.lbl_cast_badge.setStyleSheet(
            f"font-size:10px; font-weight:700; color:{ACCENT_ON}; background:{ACCENT}; "
            f"border-radius:3px; padding:0 4px;"
        )
        self.lbl_cast_badge.hide()
        cast_row = metrics.itemAt(metrics.count() - 1).layout()
        cast_row.insertWidget(1, self.lbl_cast_badge, 0)
        self.lbl_mouse = self._row(metrics, "拉线")
        body.addLayout(metrics, 1)

        self.lbl_phase = QLabel("待\n机")
        self.lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phase.setFixedWidth(18)
        self.lbl_phase.setWordWrap(True)
        self.lbl_phase.setToolTip("当前阶段")
        self.lbl_phase.setStyleSheet(
            f"font-size:11px; font-weight:700; color:{TEXT_FAINT}; "
            f"background:transparent; line-height: 1.1;"
        )
        body.addWidget(self.lbl_phase, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(body)

        self.lbl_last = QLabel("")
        self.lbl_last.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_last.setStyleSheet(
            f"font-size:10px; color:{TEXT_FAINT}; background:transparent;"
        )
        self.lbl_last.hide()
        root.addWidget(self.lbl_last)

        # 透明滑条 + 小「主界面」同一行，省高度
        foot = QHBoxLayout()
        foot.setSpacing(4)
        op_cap = QLabel("透明")
        op_cap.setStyleSheet(
            f"font-size:10px; color:{TEXT_FAINT}; background:transparent;"
        )
        foot.addWidget(op_cap)
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(45, 100)
        self.sld_opacity.setValue(88)
        self.sld_opacity.setFixedHeight(14)
        self.sld_opacity.setToolTip("浮窗透明度")
        self.sld_opacity.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                height: 3px; background: {TEXT_FAINT}; border-radius: 1px;
            }}
            QSlider::handle:horizontal {{
                width: 10px; margin: -4px 0; border-radius: 5px;
                background: {ACCENT};
            }}
            """
        )
        self.sld_opacity.valueChanged.connect(self._on_opacity_slider)
        foot.addWidget(self.sld_opacity, 1)
        self.lbl_opacity = QLabel("88%")
        self.lbl_opacity.setFixedWidth(30)
        self.lbl_opacity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_opacity.setStyleSheet(
            f"font-size:10px; color:{TEXT_MUTED}; background:transparent;"
        )
        foot.addWidget(self.lbl_opacity)
        self.btn_expand = QPushButton("主界面")
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setToolTip("切回完整调试界面")
        self.btn_expand.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.btn_expand.setStyleSheet(
            f"""
            QPushButton {{
                background: {ACCENT};
                color: {ACCENT_ON};
                border: none;
                border-radius: 4px;
                padding: 2px 8px;
                font-weight: 600;
                min-height: 0;
            }}
            QPushButton:hover {{ background: #4ac9b0; }}
            """
        )
        self.btn_expand.clicked.connect(self.expand_requested.emit)
        foot.addWidget(self.btn_expand)
        root.addLayout(foot)

        self._steady_key = "idle"
        self._flash_until = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._apply_phase("idle")
        self.set_metrics(pos="—", cast="—", mouse="—")

    @staticmethod
    def _row(parent_layout: QVBoxLayout, title: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        cap = QLabel(title)
        cap.setFixedWidth(28)
        cap.setStyleSheet(
            f"font-size:11px; font-weight:600; color:{TEXT_FAINT}; background:transparent;"
        )
        val = QLabel("—")
        val.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{TEXT_MUTED}; background:transparent;"
        )
        row.addWidget(cap)
        row.addWidget(val, 1)
        parent_layout.addLayout(row)
        return val

    def preferred_size(self) -> tuple[int, int]:
        """紧凑窗建议尺寸（字号不变，靠布局收紧）。"""
        hint = self.sizeHint()
        return max(168, hint.width()), max(118, hint.height())

    def _apply_panel_chrome(self, accent: str | None = None) -> None:
        bg = SURFACE if accent else BG
        self.setStyleSheet(
            f"QWidget#hudPanel {{ background: {bg}; border: none; border-radius: 8px; }}"
        )

    def set_opacity_value(self, opacity: float) -> None:
        pct = int(round(max(0.45, min(1.0, float(opacity))) * 100))
        self.sld_opacity.blockSignals(True)
        self.sld_opacity.setValue(pct)
        self.sld_opacity.blockSignals(False)
        self.lbl_opacity.setText(f"{pct}%")

    def _on_opacity_slider(self, value: int) -> None:
        self.lbl_opacity.setText(f"{int(value)}%")
        self.opacity_changed.emit(float(value) / 100.0)

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
        self.lbl_last.setText(f"{label} · {ts}")
        self.lbl_last.show()

    def set_metrics(
        self,
        *,
        pos: str,
        cast: str,
        mouse: str,
        pos_color: str | None = None,
        cast_color: str | None = None,
        mouse_color: str | None = None,
    ) -> None:
        self.lbl_pos.setText(pos)
        self.lbl_pos.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{pos_color or TEXT_MUTED}; "
            f"background:transparent;"
        )
        self.lbl_cast.setText(cast)
        self.lbl_cast.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{cast_color or TEXT_MUTED}; "
            f"background:transparent;"
        )
        self.lbl_mouse.setText(mouse)
        self.lbl_mouse.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{mouse_color or TEXT_MUTED}; "
            f"background:transparent;"
        )

    @staticmethod
    def _vertical_label(text: str) -> str:
        """阶段名竖排：一字一行。"""
        chars = [c for c in text if c not in "· "]
        return "\n".join(chars) if chars else text

    def _apply_phase(self, key: str) -> None:
        label, color = _PHASE_STYLE.get(key, _PHASE_STYLE["idle"])
        self.lbl_phase.setText(self._vertical_label(label))
        self.lbl_phase.setToolTip(label)
        self.lbl_phase.setStyleSheet(
            f"font-size:11px; font-weight:700; color:{color}; "
            f"background:transparent;"
        )
        self._apply_panel_chrome(color if key in _CHROME_FLASH else None)

    def set_cast_live(self, live: bool) -> None:
        self.lbl_cast_badge.setVisible(bool(live))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.sld_opacity.geometry().contains(event.position().toPoint()):
                super().mousePressEvent(event)
                return
            if self.btn_expand.geometry().contains(event.position().toPoint()):
                super().mousePressEvent(event)
                return
            win = self.window()
            self._drag_origin = (
                event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)
