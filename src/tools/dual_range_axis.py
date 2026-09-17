"""0～100 数轴：两段可拖区间（按住 / 松开），不重叠且至少间隔 gap。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_MIN = 0.0
_MAX = 100.0
_DEFAULT_GAP = 1.0
_STEP = 0.1  # 一位小数


def _q(v: float) -> float:
    """量化到 0.1。"""
    return round(float(v) / _STEP) * _STEP


class DualRangeAxis(QWidget):
    """
    左段=按住抽样范围，右段=松开抽样范围。
    拖端点或整段；两段不得重叠，且右段起点 − 左段终点 ≥ min_gap。
    端点精度 0.1。
    """

    rangesChanged = Signal(float, float, float, float)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        min_gap: float = _DEFAULT_GAP,
        press: tuple[float, float] = (40.0, 70.0),
        release: tuple[float, float] = (75.0, 90.0),
    ) -> None:
        super().__init__(parent)
        self.min_gap = float(min_gap)
        self._plo, self._phi = float(press[0]), float(press[1])
        self._rlo, self._rhi = float(release[0]), float(release[1])
        self._drag: str | None = None
        self._drag_origin = 0.0
        self._drag_snapshot: tuple[float, float, float, float] | None = None
        self.setMinimumHeight(56)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._normalize()

    def ranges(self) -> tuple[float, float, float, float]:
        return self._plo, self._phi, self._rlo, self._rhi

    def setRanges(
        self, plo: float, phi: float, rlo: float, rhi: float, *, emit: bool = True
    ) -> None:
        self._plo, self._phi, self._rlo, self._rhi = (
            float(plo),
            float(phi),
            float(rlo),
            float(rhi),
        )
        self._normalize()
        self.update()
        if emit:
            self.rangesChanged.emit(*self.ranges())

    def _normalize(self) -> None:
        gap = self.min_gap
        plo = max(_MIN, min(_MAX, _q(self._plo)))
        phi = max(_MIN, min(_MAX, _q(self._phi)))
        rlo = max(_MIN, min(_MAX, _q(self._rlo)))
        rhi = max(_MIN, min(_MAX, _q(self._rhi)))
        if plo > phi:
            plo, phi = phi, plo
        if rlo > rhi:
            rlo, rhi = rhi, rlo
        # 保证间隔
        if phi + gap > rlo:
            mid = (phi + rlo) / 2.0
            phi = _q(mid - gap / 2.0)
            rlo = _q(mid + gap / 2.0)
            if phi < plo:
                plo = phi
            if rhi < rlo:
                rhi = rlo
        # 仍不够空间则压缩
        if rlo - phi < gap:
            phi = max(plo, min(phi, _MAX - gap - _STEP))
            rlo = _q(phi + gap)
            if rhi < rlo:
                rhi = min(_MAX, _q(rlo + _STEP))
        if rhi > _MAX:
            rhi = _MAX
        if plo < _MIN:
            plo = _MIN
        self._plo, self._phi, self._rlo, self._rhi = (
            _q(plo),
            _q(phi),
            _q(rlo),
            _q(rhi),
        )

    def _track(self) -> QRectF:
        return QRectF(12, 22, max(1.0, self.width() - 24), 14)

    def _x_of(self, v: float) -> float:
        track = self._track()
        t = (v - _MIN) / (_MAX - _MIN)
        return track.left() + t * track.width()

    def _v_of(self, x: float) -> float:
        track = self._track()
        if track.width() <= 1:
            return _MIN
        t = (x - track.left()) / track.width()
        return max(_MIN, min(_MAX, _MIN + t * (_MAX - _MIN)))

    def _handle_at(self, pos: QPointF) -> str | None:
        hits: list[tuple[float, str]] = []
        for name, v in (
            ("plo", self._plo),
            ("phi", self._phi),
            ("rlo", self._rlo),
            ("rhi", self._rhi),
        ):
            hx = self._x_of(v)
            dist = abs(pos.x() - hx)
            if dist <= 10 and 8 <= pos.y() <= 48:
                hits.append((dist, name))
        if hits:
            hits.sort()
            return hits[0][1]
        # 整段
        x = pos.x()
        y = pos.y()
        if 18 <= y <= 42:
            if self._x_of(self._plo) <= x <= self._x_of(self._phi):
                return "press_body"
            if self._x_of(self._rlo) <= x <= self._x_of(self._rhi):
                return "release_body"
        return None

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self._track()
        # 底轴
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e8eaed"))
        p.drawRoundedRect(track, 4, 4)
        # 间隔区
        gap_l = self._x_of(self._phi)
        gap_r = self._x_of(self._rlo)
        if gap_r > gap_l:
            p.setBrush(QColor("#d0d4da"))
            p.drawRect(QRectF(gap_l, track.top(), gap_r - gap_l, track.height()))
        # 按住段
        p.setBrush(QColor("#3d8bfd"))
        p.drawRoundedRect(
            QRectF(
                self._x_of(self._plo),
                track.top(),
                max(2.0, self._x_of(self._phi) - self._x_of(self._plo)),
                track.height(),
            ),
            3,
            3,
        )
        # 松开段
        p.setBrush(QColor("#2bb673"))
        p.drawRoundedRect(
            QRectF(
                self._x_of(self._rlo),
                track.top(),
                max(2.0, self._x_of(self._rhi) - self._x_of(self._rlo)),
                track.height(),
            ),
            3,
            3,
        )
        # 刻度
        font = QFont(self.font())
        font.setPointSize(max(9, font.pointSize() - 1))
        p.setFont(font)
        p.setPen(QColor("#787c80"))
        for tick in (0, 25, 50, 75, 100):
            x = self._x_of(tick)
            p.drawLine(QPointF(x, track.bottom() + 2), QPointF(x, track.bottom() + 6))
            p.drawText(
                QRectF(x - 14, track.bottom() + 6, 28, 14),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(tick),
            )
        # 端点
        for v, color in (
            (self._plo, "#1a5fb4"),
            (self._phi, "#1a5fb4"),
            (self._rlo, "#1b7a4a"),
            (self._rhi, "#1b7a4a"),
        ):
            cx = self._x_of(v)
            cy = track.center().y()
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
        # 顶部数值
        p.setPen(QColor("#3c4043"))
        label = (
            f"按住 U({self._plo:.1f}～{self._phi:.1f})   "
            f"间隔≥{self.min_gap:.1f}   "
            f"松开 U({self._rlo:.1f}～{self._rhi:.1f})"
        )
        p.drawText(
            QRectF(12, 2, self.width() - 24, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._handle_at(event.position())
        if hit is None:
            return
        self._drag = hit
        self._drag_origin = self._v_of(event.position().x())
        self._drag_snapshot = self.ranges()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is None:
            hit = self._handle_at(event.position())
            if hit in ("press_body", "release_body"):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif hit:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        v = _q(self._v_of(event.position().x()))
        gap = self.min_gap
        plo, phi, rlo, rhi = self._drag_snapshot or self.ranges()
        which = self._drag
        if which == "plo":
            plo = max(_MIN, min(v, phi))
        elif which == "phi":
            phi = max(plo, min(v, rlo - gap))
        elif which == "rlo":
            rlo = min(rhi, max(v, phi + gap))
        elif which == "rhi":
            rhi = min(_MAX, max(v, rlo))
        elif which == "press_body":
            splo, sphi, srlo, _srhi = self._drag_snapshot
            width = sphi - splo
            delta = v - _q(self._drag_origin)
            nlo = splo + delta
            nhi = nlo + width
            max_hi = srlo - gap
            if nhi > max_hi:
                nhi = max_hi
                nlo = nhi - width
            if nlo < _MIN:
                nlo = _MIN
                nhi = nlo + width
                if nhi > max_hi:
                    nhi = max_hi
                    nlo = max(_MIN, nhi - width)
            plo, phi = _q(nlo), _q(nhi)
        elif which == "release_body":
            _splo, sphi, srlo, srhi = self._drag_snapshot
            width = srhi - srlo
            delta = v - _q(self._drag_origin)
            nlo = srlo + delta
            nhi = nlo + width
            min_lo = sphi + gap
            if nlo < min_lo:
                nlo = min_lo
                nhi = nlo + width
            if nhi > _MAX:
                nhi = _MAX
                nlo = nhi - width
                if nlo < min_lo:
                    nlo = min_lo
                    nhi = min(_MAX, nlo + width)
            rlo, rhi = _q(nlo), _q(nhi)
        self._plo, self._phi, self._rlo, self._rhi = plo, phi, rlo, rhi
        self._normalize()
        self.update()
        self.rangesChanged.emit(*self.ranges())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
            self._drag_snapshot = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.rangesChanged.emit(*self.ranges())
