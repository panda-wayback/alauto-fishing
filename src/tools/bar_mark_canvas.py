"""条界标记画布：参考图 + 程序界（次）+ 手动界（主，可拖）。"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

_MIN_BAR_W = 40.0
_HIT_PX = 10


def _rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class BarMarkCanvas(QLabel):
    """显示识别参考图；拖左右竖线改手动条界。"""

    manual_changed = Signal(object)  # Bar box (l,t,w,h) or None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#1c1e22; color:#888; border:1px solid #373a40;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._rgb: np.ndarray | None = None
        self._pixmap = QPixmap()
        self._scale = 1.0
        self._offset = QPoint(0, 0)
        self._program: tuple[float, float, float, float] | None = None
        self._manual: tuple[float, float, float, float] | None = None
        self._drag: str | None = None  # "L" | "R"
        self.setText("BAR · 等待参考图")

    def set_rgb(self, rgb: np.ndarray | None) -> None:
        self._rgb = None if rgb is None else np.ascontiguousarray(rgb)
        if self._rgb is None:
            self._pixmap = QPixmap()
            self.setText("BAR · 等待参考图")
        else:
            self.setText("")
            self._pixmap = _rgb_to_pixmap(self._rgb)
            self._layout_pixmap()
        self.update()

    def set_program_bar(
        self, box: tuple[float, float, float, float] | None
    ) -> None:
        self._program = box
        self.update()

    def set_manual_bar(
        self, box: tuple[float, float, float, float] | None
    ) -> None:
        self._manual = box
        self.update()

    @property
    def manual_bar(self) -> tuple[float, float, float, float] | None:
        return self._manual

    def clear_manual(self) -> None:
        if self._manual is None:
            return
        self._manual = None
        self.manual_changed.emit(None)
        self.update()

    def ensure_manual_from_program(self) -> None:
        """无手动时，用程序界或默认比例生成可拖手动界。"""
        if self._manual is not None or self._rgb is None:
            return
        h, w = self._rgb.shape[:2]
        if self._program is not None:
            self._manual = self._program
        else:
            left = w * 0.08
            right = w * 0.92
            self._manual = (left, h * 0.25, right - left, h * 0.45)
        self.manual_changed.emit(self._manual)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._pixmap.isNull():
            self._layout_pixmap()

    def _layout_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        cw, ch = max(1, self.width()), max(1, self.height())
        self._scale = min(cw / pw, ch / ph, 1.0)
        nw, nh = max(1, int(pw * self._scale)), max(1, int(ph * self._scale))
        self._offset = QPoint((cw - nw) // 2, (ch - nh) // 2)

    def _img_to_widget_x(self, x: float) -> int:
        return int(self._offset.x() + x * self._scale)

    def _widget_to_img(self, pos: QPoint) -> tuple[float, float] | None:
        if self._rgb is None or self._scale <= 0:
            return None
        x = (pos.x() - self._offset.x()) / self._scale
        y = (pos.y() - self._offset.y()) / self._scale
        h, w = self._rgb.shape[:2]
        if x < -2 or y < -2 or x > w + 2 or y > h + 2:
            return None
        return float(np.clip(x, 0, w - 1)), float(np.clip(y, 0, h - 1))

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        p = QPainter(self)
        nw = max(1, int(self._pixmap.width() * self._scale))
        nh = max(1, int(self._pixmap.height() * self._scale))
        p.drawPixmap(QRect(self._offset.x(), self._offset.y(), nw, nh), self._pixmap)
        if self._program is not None:
            self._draw_bar(p, self._program, QColor(80, 180, 255, 200), 1)
        if self._manual is not None:
            self._draw_bar(p, self._manual, QColor(255, 210, 40), 2)
        p.end()

    def _draw_bar(
        self,
        p: QPainter,
        box: tuple[float, float, float, float],
        color: QColor,
        width: int,
    ) -> None:
        left, top, bw, bh = box
        x0 = self._img_to_widget_x(left)
        x1 = self._img_to_widget_x(left + bw)
        y0 = int(self._offset.y() + top * self._scale)
        y1 = int(self._offset.y() + (top + max(bh, 1)) * self._scale)
        pen = QPen(color, width)
        p.setPen(pen)
        p.drawLine(x0, y0, x0, y1)
        p.drawLine(x1, y0, x1, y1)
        p.drawLine(x0, y0, x1, y0)
        p.drawLine(x0, y1, x1, y1)

    def _hit_edge(self, pos: QPoint) -> str | None:
        box = self._manual or self._program
        if box is None or self._rgb is None:
            return None
        left, _t, bw, _h = box
        x_l = self._img_to_widget_x(left)
        x_r = self._img_to_widget_x(left + bw)
        if abs(pos.x() - x_l) <= _HIT_PX:
            return "L"
        if abs(pos.x() - x_r) <= _HIT_PX:
            return "R"
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._rgb is None:
            super().mousePressEvent(event)
            return
        if self._manual is None:
            self.ensure_manual_from_program()
        edge = self._hit_edge(event.position().toPoint())
        if edge is not None:
            self._drag = edge
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._drag is None:
            hit = self._hit_edge(pos)
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if hit
                else Qt.CursorShape.ArrowCursor
            )
            super().mouseMoveEvent(event)
            return
        img = self._widget_to_img(pos)
        if img is None or self._manual is None or self._rgb is None:
            return
        x, _y = img
        left, top, bw, bh = self._manual
        right = left + bw
        h, w = self._rgb.shape[:2]
        if self._drag == "L":
            left = float(np.clip(x, 0, right - _MIN_BAR_W))
        else:
            right = float(np.clip(x, left + _MIN_BAR_W, w - 1))
        self._manual = (left, top, right - left, bh if bh > 0 else float(h))
        self.manual_changed.emit(self._manual)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)
