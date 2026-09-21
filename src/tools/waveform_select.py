"""可拖选区间的波形长条（长录音回测标注用）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    import numpy.typing as npt


class WaveformSelectWidget(QWidget):
    """
    显示整段波形；拖拽选择 [start_s, end_s]；滚轮缩放。
    绿半透明：人工水花标注；橙半透明：回测命中区间。
    """

    selection_changed = Signal(float, float)  # start_s, end_s

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        self._wave: "npt.NDArray[np.float32] | None" = None
        self._sr: int = 48000
        self._marks: list[tuple[float, float]] = []
        self._hits: list[dict[str, float]] = []
        self._sel_start_s: float = 0.0
        self._sel_end_s: float = 0.0
        self._dragging = False
        self._drag_anchor_s: float = 0.0
        # 可视窗口：占全长的比例与起点（0~1）
        self._view_start = 0.0
        self._view_span = 1.0
        self._envelope: "npt.NDArray[np.float32] | None" = None
        self._env_n = 0

    def clear(self) -> None:
        self._wave = None
        self._marks = []
        self._hits = []
        self._sel_start_s = 0.0
        self._sel_end_s = 0.0
        self._view_start = 0.0
        self._view_span = 1.0
        self._envelope = None
        self.update()

    def set_audio(
        self,
        wave: "npt.NDArray[np.float32] | None",
        samplerate: int,
        *,
        keep_view: bool = False,
    ) -> None:
        if wave is None or wave.size == 0:
            self.clear()
            return
        mono = np.asarray(wave, dtype=np.float32)
        if mono.ndim > 1:
            mono = mono.mean(axis=1)
        self._wave = mono
        self._sr = max(int(samplerate), 1)
        if not keep_view:
            self._view_start = 0.0
            self._view_span = 1.0
            self._hits = []
        self._rebuild_envelope()
        dur = self.duration_s
        if self._sel_end_s <= self._sel_start_s or self._sel_end_s > dur:
            self._sel_start_s = 0.0
            self._sel_end_s = min(0.4, dur)
            self.selection_changed.emit(self._sel_start_s, self._sel_end_s)
        self.update()

    def set_marks(self, ranges: list[tuple[float, float]]) -> None:
        self._marks = [(float(a), float(b)) for a, b in ranges]
        self.update()

    def set_hits(self, hits: list[dict[str, float]] | None) -> None:
        """回测命中：每项含 start_s/end_s（或 t_s）与 score。"""
        out: list[dict[str, float]] = []
        for h in hits or []:
            end_s = float(h.get("end_s", h.get("t_s", 0.0)))
            start_s = float(h.get("start_s", end_s))
            if end_s < start_s:
                start_s, end_s = end_s, start_s
            out.append(
                {
                    "start_s": start_s,
                    "end_s": end_s,
                    "t_s": float(h.get("t_s", end_s)),
                    "score": float(h.get("score", 0.0)),
                }
            )
        self._hits = out
        self.update()

    def set_selection(self, start_s: float, end_s: float, *, emit: bool = True) -> None:
        dur = self.duration_s
        a = max(0.0, min(float(start_s), dur))
        b = max(0.0, min(float(end_s), dur))
        if b < a:
            a, b = b, a
        self._sel_start_s = a
        self._sel_end_s = b
        self.update()
        if emit:
            self.selection_changed.emit(a, b)

    @property
    def duration_s(self) -> float:
        if self._wave is None:
            return 0.0
        return float(len(self._wave) / self._sr)

    @property
    def selection(self) -> tuple[float, float]:
        return self._sel_start_s, self._sel_end_s

    def _rebuild_envelope(self) -> None:
        if self._wave is None or self._wave.size == 0:
            self._envelope = None
            self._env_n = 0
            return
        # 预计算较密包络，绘制时再按像素抽
        target = min(4000, max(200, len(self._wave) // 64))
        bucket = max(1, len(self._wave) // target)
        n = len(self._wave) // bucket
        if n <= 0:
            self._envelope = np.abs(self._wave[:1]).astype(np.float32)
            self._env_n = 1
            return
        trimmed = self._wave[: n * bucket].reshape(n, bucket)
        peaks = np.max(np.abs(trimmed), axis=1).astype(np.float32)
        peak = float(peaks.max()) if peaks.size else 1.0
        if peak < 1e-8:
            peak = 1.0
        self._envelope = peaks / peak
        self._env_n = n

    def _view_sample_range(self) -> tuple[int, int]:
        if self._wave is None:
            return 0, 0
        n = len(self._wave)
        i0 = int(self._view_start * n)
        i1 = int((self._view_start + self._view_span) * n)
        return max(0, i0), min(n, max(i0 + 1, i1))

    def _x_to_time(self, x: float) -> float:
        w = max(self.width(), 1)
        i0, i1 = self._view_sample_range()
        if i1 <= i0:
            return 0.0
        frac = max(0.0, min(1.0, x / w))
        sample = i0 + frac * (i1 - i0)
        return sample / self._sr

    def _time_to_x(self, t_s: float) -> float:
        w = max(self.width(), 1)
        i0, i1 = self._view_sample_range()
        if i1 <= i0:
            return 0.0
        sample = t_s * self._sr
        frac = (sample - i0) / (i1 - i0)
        return max(0.0, min(1.0, frac)) * w

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1c1c1e"))
        if self._wave is None or self._envelope is None or self._env_n <= 0:
            p.setPen(QColor("#8e8e93"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "加载或保存长录音后，在此拖选水花区间")
            return

        w = self.width()
        h = self.height()
        mid = h * 0.5
        i0, i1 = self._view_sample_range()
        n = len(self._wave)
        # 包络索引映射到可视样本
        e0 = int(i0 / n * self._env_n)
        e1 = int(i1 / n * self._env_n)
        e0 = max(0, min(self._env_n - 1, e0))
        e1 = max(e0 + 1, min(self._env_n, e1))
        env = self._envelope[e0:e1]
        # 人工水花标注（绿）
        for a, b in self._marks:
            x0 = self._time_to_x(a)
            x1 = self._time_to_x(b)
            p.fillRect(int(x0), 0, max(1, int(x1 - x0)), h, QColor(52, 199, 89, 70))
        # 回测命中（橙）
        for hit in self._hits:
            x0 = self._time_to_x(hit["start_s"])
            x1 = self._time_to_x(hit["end_s"])
            p.fillRect(int(x0), 0, max(2, int(x1 - x0)), h, QColor(255, 149, 0, 90))
            p.setPen(QPen(QColor("#ff9500"), 2))
            p.drawLine(int(x1), 0, int(x1), h)
        # 当前选区
        sx0 = self._time_to_x(self._sel_start_s)
        sx1 = self._time_to_x(self._sel_end_s)
        p.fillRect(int(sx0), 0, max(1, int(sx1 - sx0)), h, QColor(10, 132, 255, 70))
        p.setPen(QPen(QColor("#0a84ff"), 1))
        p.drawLine(int(sx0), 0, int(sx0), h)
        p.drawLine(int(sx1), 0, int(sx1), h)

        # 波形
        p.setPen(QPen(QColor("#d1d1d6"), 1))
        cols = max(1, w)
        for x in range(cols):
            fi = e0 + (x / cols) * (e1 - e0)
            idx = int(fi)
            if idx < 0 or idx >= self._env_n:
                continue
            amp = float(self._envelope[idx])
            y = amp * (h * 0.42)
            p.drawLine(x, int(mid - y), x, int(mid + y))

        # 命中分数（画在区间中部上方，避免挤成一团时只标最高分）
        p.setPen(QColor("#ffcc80"))
        for hit in self._hits:
            x0 = self._time_to_x(hit["start_s"])
            x1 = self._time_to_x(hit["end_s"])
            cx = int((x0 + x1) * 0.5)
            if cx < 0 or cx > w:
                continue
            p.drawText(cx - 18, 16, f"{hit['score']:.2f}")

        # 时间刻度 + 图例
        p.setPen(QColor("#8e8e93"))
        t0 = i0 / self._sr
        t1 = i1 / self._sr
        p.drawText(6, 14, f"{t0:.2f}s")
        p.drawText(w - 64, 14, f"{t1:.2f}s")
        legend = f"选区 [{self._sel_start_s:.2f}, {self._sel_end_s:.2f}]s"
        if self._marks:
            legend += f" · 绿标注{len(self._marks)}"
        if self._hits:
            legend += f" · 橙命中{len(self._hits)}"
        p.drawText(6, h - 6, legend)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._wave is None or event.button() != Qt.MouseButton.LeftButton:
            return
        t = self._x_to_time(event.position().x())
        self._dragging = True
        self._drag_anchor_s = t
        self.set_selection(t, t)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging or self._wave is None:
            return
        t = self._x_to_time(event.position().x())
        self.set_selection(self._drag_anchor_s, t)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            a, b = self.selection
            if b - a < 0.02 and self.duration_s > 0:
                # 单击：扩成一小段便于再拖
                mid = a
                self.set_selection(max(0.0, mid - 0.1), min(self.duration_s, mid + 0.1))

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._wave is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        # 以鼠标位置为中心缩放
        mx = event.position().x() / max(self.width(), 1)
        focus = self._view_start + mx * self._view_span
        factor = 0.8 if delta > 0 else 1.25
        new_span = min(1.0, max(0.02, self._view_span * factor))
        new_start = focus - mx * new_span
        new_start = max(0.0, min(1.0 - new_span, new_start))
        self._view_span = new_span
        self._view_start = new_start
        self.update()

    def zoom_all(self) -> None:
        self._view_start = 0.0
        self._view_span = 1.0
        self.update()

    def zoom_to_selection(self) -> None:
        dur = self.duration_s
        if dur <= 0:
            return
        a, b = self.selection
        pad = max(0.05, (b - a) * 0.3)
        a = max(0.0, a - pad)
        b = min(dur, b + pad)
        self._view_start = a / dur
        self._view_span = max(0.02, (b - a) / dur)
        self.update()
