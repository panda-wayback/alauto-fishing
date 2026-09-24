"""MONITOR 画布：显示 RGB，框选模式下拖出 ROI。"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

from autofish.detect.bobber import BobberHit
from tools.shell_theme import preview_canvas_qss


def rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def draw_rect(
    rgb: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    fh, fw = rgb.shape[:2]
    x0 = max(0, min(fw - 1, x))
    y0 = max(0, min(fh - 1, y))
    x1 = max(0, min(fw - 1, x + max(w, 1) - 1))
    y1 = max(0, min(fh - 1, y + max(h, 1) - 1))
    if x1 <= x0 or y1 <= y0:
        return
    t = max(1, thickness)
    rgb[y0 : y0 + t, x0 : x1 + 1] = color
    rgb[y1 - t + 1 : y1 + 1, x0 : x1 + 1] = color
    rgb[y0 : y1 + 1, x0 : x0 + t] = color
    rgb[y0 : y1 + 1, x1 - t + 1 : x1 + 1] = color


def overlay_hit(rgb: np.ndarray, hit: BobberHit | None) -> np.ndarray:
    """叠层：有条画条框；有漂画命中点（可有漂无条）。"""
    if hit is None:
        return rgb
    vis = rgb.copy()
    fh, fw = vis.shape[:2]
    if hit.bar_width > 0:
        zx, zy = int(hit.bar_left), int(hit.bar_top)
        zw, zh = int(hit.bar_width), int(hit.bar_height)
        draw_rect(vis, zx, zy, zw, zh, (0, 230, 120), thickness=2)
        y0 = max(0, zy - max(6, zh // 2))
        y1 = min(fh, zy + zh + 2)
        x0, x1 = max(0, zx), min(fw, zx + zw)
        draw_rect(vis, x0, y0, x1 - x0, y1 - y0, (255, 200, 40), thickness=1)
        mid_y0 = zy
        mid_y1 = min(fh - 1, zy + max(zh, 1) - 1)
        if 0 <= zx < fw:
            vis[mid_y0 : mid_y1 + 1, zx] = (0, 255, 180)
        right = min(fw - 1, zx + max(zw, 1) - 1)
        if 0 <= right < fw:
            vis[mid_y0 : mid_y1 + 1, right] = (0, 255, 180)
    x, y = int(hit.x), int(hit.y)
    if 0 <= x < fw and 0 <= y < fh:
        vis[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = (0, 210, 230)
        if hit.bar_width <= 0:
            for dx, dy in ((-6, 0), (6, 0), (0, -6), (0, 6)):
                xx, yy = x + dx, y + dy
                if 0 <= xx < fw and 0 <= yy < fh:
                    vis[yy, xx] = (255, 220, 40)
    return vis


class ImageCanvas(QLabel):
    """显示 RGB；框选模式下拖拽出 ROI。"""

    selection_changed = Signal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(preview_canvas_qss())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._rgb: np.ndarray | None = None
        self._pixmap = QPixmap()
        self._selecting = False
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._scale = 1.0
        self._offset = QPoint(0, 0)
        self.setText(title)

    def set_rgb(self, rgb: np.ndarray | None) -> None:
        self._rgb = None if rgb is None else np.ascontiguousarray(rgb)
        self._rebuild()

    def set_selecting(self, on: bool) -> None:
        self._selecting = on
        if not on:
            self._drag_start = self._drag_end = None
        self.update()

    def selection_in_image(self) -> tuple[int, int, int, int] | None:
        """返回图像坐标 (left, top, width, height)。"""
        if self._rgb is None or self._drag_start is None or self._drag_end is None:
            return None
        a = self._widget_to_image(self._drag_start)
        b = self._widget_to_image(self._drag_end)
        if a is None or b is None:
            return None
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return x0, y0, x1 - x0, y1 - y0

    def _rebuild(self) -> None:
        if self._rgb is None:
            self._pixmap = QPixmap()
            self.setText(self._title)
            return
        self.setText("")
        self._pixmap = rgb_to_pixmap(self._rgb)
        self._layout_pixmap()
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

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        p = QPainter(self)
        nw = max(1, int(self._pixmap.width() * self._scale))
        nh = max(1, int(self._pixmap.height() * self._scale))
        target = QRect(self._offset.x(), self._offset.y(), nw, nh)
        p.drawPixmap(target, self._pixmap)
        if self._selecting and self._drag_start and self._drag_end:
            pen = QPen(QColor(70, 160, 230), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(QRect(self._drag_start, self._drag_end).normalized())
        p.end()

    def _widget_to_image(self, pos: QPoint) -> tuple[int, int] | None:
        if self._rgb is None or self._scale <= 0:
            return None
        x = int((pos.x() - self._offset.x()) / self._scale)
        y = int((pos.y() - self._offset.y()) / self._scale)
        h, w = self._rgb.shape[:2]
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        return x, y

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self._drag_end = event.position().toPoint()
            self.update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._selecting and self._drag_start is not None:
            self._drag_end = event.position().toPoint()
            self.update()
            self.selection_changed.emit()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._drag_end = event.position().toPoint()
            self.update()
            self.selection_changed.emit()
        else:
            super().mouseReleaseEvent(event)
