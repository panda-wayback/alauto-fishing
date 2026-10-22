"""独立幕布：标定分辨率无关的透视抛杆贴地环。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autofish.cast_calibration import (
    DEFAULT_CAST_CIRCLE_PATH,
    CastCircle,
    load_cast_circle,
    save_cast_circle,
)
from autofish.locate.roi import primary_screen_size
from tools.shell_theme import global_qss

DEFAULT_ANGLE = 30.0
CANVAS_W = 720
RING_RATIOS = (0.25, 0.5, 0.75, 1.0)


class CastCanvas(QFrame):
    """按主屏纵横比缩放的幕布；画透视贴地环。"""

    def __init__(self, width: int, height: int, circle: CastCircle, on_change) -> None:
        super().__init__()
        self.canvas_w = width
        self.canvas_h = height
        self.circle = circle
        self.on_change = on_change
        self._dragging = False
        self.setFixedSize(width, height)
        self.setStyleSheet("background:#11151c;border:1px solid #2a313c;")
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_circle(self, circle: CastCircle) -> None:
        self.circle = circle
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for ring in RING_RATIOS:
            pts = self.circle.reference_polygon(
                ring, self.canvas_w, self.canvas_h, 160
            )
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            alpha = 120 if ring < 1.0 else 235
            width = 1 if ring < 1.0 else 2
            p.setPen(QPen(QColor(255, 210, 60, alpha), width))
            p.drawPath(path)

        ax, ay = self.circle.anchor(self.canvas_w, self.canvas_h)
        center = QPoint(int(round(ax)), int(round(ay)))
        p.setPen(QPen(QColor(255, 90, 90, 240), 2))
        p.drawLine(center - QPoint(9, 0), center + QPoint(9, 0))
        p.drawLine(center - QPoint(0, 9), center + QPoint(0, 9))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._move_center(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._move_center(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = 1 if event.angleDelta().y() > 0 else -1
        current = self.circle.radius_for(self.canvas_w, self.canvas_h)
        new_px = max(20.0, min(self.canvas_h * 0.9, current + delta * 6.0))
        new_ratio = new_px / min(self.canvas_w, self.canvas_h)
        self.circle = self.circle.with_radius_ratio(new_ratio)
        self.on_change(self.circle)
        self.update()

    def _move_center(self, pos: QPoint) -> None:
        cx = min(max(pos.x() / self.canvas_w, 0.02), 0.98)
        cy = min(max(pos.y() / self.canvas_h, 0.02), 0.98)
        self.circle = self.circle.with_anchor_ratio(cx, cy)
        self.on_change(self.circle)
        self.update()


class CastCalibrationWindow(QWidget):
    """标定值全部为比例，任何屏幕按自身尺寸自适应。"""

    def __init__(
        self,
        circle_path: Path = DEFAULT_CAST_CIRCLE_PATH,
        screen_size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self.circle_path = Path(circle_path)
        self.saved_circle: CastCircle | None = None
        self.setWindowTitle("标定抛杆圆")
        self.setStyleSheet(global_qss())

        # 仅用于幕布纵横比；保存数据不依赖这些像素。
        self.screen_w, self.screen_h = (
            screen_size if screen_size is not None else primary_screen_size()
        )
        self.canvas_h = max(240, round(CANVAS_W * self.screen_h / self.screen_w))

        self.circle = self._load_circle()
        self.canvas = CastCanvas(
            CANVAS_W, self.canvas_h, self.circle, self._on_canvas_changed
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(
            QLabel("拖红十字到人物脚下；调俯视角度与大小（也可滚轮）。保存的是比例，换屏幕自适应。")
        )
        layout.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout()
        row.addWidget(QLabel("俯视角度"))
        self.slider_angle = QSlider(Qt.Orientation.Horizontal)
        self.slider_angle.setRange(10, 90)
        self.slider_angle.setValue(int(round(self.circle.angle_deg)))
        self.lbl_angle = QLabel(f"{self.circle.angle_deg:.0f}°")
        self.lbl_angle.setMinimumWidth(44)
        self.slider_angle.valueChanged.connect(self._on_angle_changed)
        row.addWidget(self.slider_angle, 1)
        row.addWidget(self.lbl_angle)
        layout.addLayout(row)

        row_size = QHBoxLayout()
        row_size.addWidget(QLabel("大小"))
        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(5, 90)  # 屏幕短边的百分比
        self.slider_size.setValue(int(round(self.circle.radius_ratio * 100)))
        self.lbl_size = QLabel()
        self.lbl_size.setMinimumWidth(56)
        self.slider_size.valueChanged.connect(self._on_size_changed)
        row_size.addWidget(self.slider_size, 1)
        row_size.addWidget(self.lbl_size)
        layout.addLayout(row_size)

        row2 = QHBoxLayout()
        self.lbl_values = QLabel()
        row2.addWidget(self.lbl_values, 1)
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("btnPrimary")
        self.btn_save.clicked.connect(self._save)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("btnGhost")
        self.btn_close.clicked.connect(self.close)
        row2.addWidget(self.btn_save)
        row2.addWidget(self.btn_close)
        layout.addLayout(row2)
        self._refresh_values()

    def _load_circle(self) -> CastCircle:
        try:
            return load_cast_circle(self.circle_path)
        except (OSError, ValueError, KeyError, TypeError):
            return CastCircle(0.5, 0.62, DEFAULT_ANGLE)

    def _on_canvas_changed(self, circle: CastCircle) -> None:
        self.circle = circle
        self._sync_size_slider()
        self._refresh_values()

    def _on_angle_changed(self, value: int) -> None:
        self.circle = self.circle.with_angle(float(value))
        self.lbl_angle.setText(f"{value}°")
        self.canvas.set_circle(self.circle)
        self._refresh_values()

    def _on_size_changed(self, value: int) -> None:
        self.circle = self.circle.with_radius_ratio(value / 100.0)
        self.canvas.set_circle(self.circle)
        self._refresh_values()

    def _sync_size_slider(self) -> None:
        percent = int(round(self.circle.radius_ratio * 100))
        if percent != self.slider_size.value():
            self.slider_size.blockSignals(True)
            self.slider_size.setValue(percent)
            self.slider_size.blockSignals(False)
        self.lbl_size.setText(f"{percent}%")

    def _refresh_values(self) -> None:
        self._sync_size_slider()
        self.lbl_values.setText(
            f"圆心=({self.circle.cx:.3f}, {self.circle.cy:.3f})  "
            f"角度={self.circle.angle_deg:.0f}°  "
            f"大小={self.circle.radius_ratio * 100:.0f}% 短边"
        )

    def _save(self) -> None:
        save_cast_circle(self.circle, self.circle_path)
        self.saved_circle = self.circle
        self.setWindowTitle(f"已保存：{self.circle_path}")


def launch_cast_calibration(
    *, circle_path: Path | str | None = None
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(global_qss())
    path = Path(circle_path) if circle_path is not None else DEFAULT_CAST_CIRCLE_PATH
    win = CastCalibrationWindow(path)
    win.show()
    return int(app.exec())


def main(argv: list[str] | None = None) -> int:
    return launch_cast_calibration()


if __name__ == "__main__":
    raise SystemExit(main())
