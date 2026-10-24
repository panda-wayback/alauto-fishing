"""自动抛杆配置页：次数区间、快捷键、满蓄秒数、收竿等待区间、本页日志。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.dual_range_axis import SingleRangeBar
from tools.shell_log import PageLogPopup
from tools.shell_theme import TEXT_MUTED

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_cast_page(host: "PreviewApp") -> QWidget:
    page = QWidget()
    page_l = QVBoxLayout(page)
    page_l.setContentsMargins(0, 0, 0, 0)
    page_l.setSpacing(6)

    host._cast_log_popup = PageLogPopup(
        host,
        "自动抛竿 · 日志",
        object_name="mainLog",
        placeholder="最新在上 · 第几次 · 按下秒数 · 拉漂后等待 · 快捷键…",
    )
    host.cast_log = host._cast_log_popup.editor
    head = QHBoxLayout()
    tip = QLabel(
        "主控勾选「自动抛竿」后：光标旁认出水面漂再右键开始；任务中任意时刻右键立刻结束；"
        "F8 / F9 备用。蓄力：目标比例 × 满蓄秒数，再加约 ±0.1 秒抖动后松开。"
        "下一杆须等拉漂结束后再等待（默认 3 秒）。标定请用 make cast-calib。"
    )
    tip.setWordWrap(True)
    tip.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
    head.addWidget(tip, 1)
    head.addWidget(host._cast_log_popup.make_button(), 0)
    page_l.addLayout(head)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 0, 4, 0)
    lay.setSpacing(8)

    batch = QGroupBox("本轮抛杆")
    batch_l = QVBoxLayout(batch)
    batch_l.setSpacing(8)
    batch_l.addWidget(
        QLabel("抛几次 · 1～10 · 每次开始时在区间内随机出本轮总次数")
    )
    s = host._settings
    host.bar_cast_count = SingleRangeBar(
        vmin=1.0,
        vmax=10.0,
        value=(float(s.cast_count_lo), float(s.cast_count_hi)),
        unit="次",
        title="次数",
        min_span=0.0,
        step=1.0,
    )
    host.bar_cast_count.rangeChanged.connect(host._on_cast_count_changed)
    batch_l.addWidget(host.bar_cast_count)

    row_full = QHBoxLayout()
    row_full.addWidget(QLabel("满蓄秒数"))
    host.spin_cast_full_charge = QDoubleSpinBox()
    host.spin_cast_full_charge.setRange(0.05, 5.0)
    host.spin_cast_full_charge.setSingleStep(0.05)
    host.spin_cast_full_charge.setDecimals(2)
    host.spin_cast_full_charge.setValue(float(host._settings.cast_full_charge_s))
    host.spin_cast_full_charge.setToolTip(
        "目标比例=1 时的按下时长；实际按下 = 满蓄秒数 × 目标比例"
    )
    host.spin_cast_full_charge.valueChanged.connect(host._on_cast_full_charge_changed)
    row_full.addWidget(host.spin_cast_full_charge)
    row_full.addStretch(1)
    batch_l.addLayout(row_full)

    row_hk = QHBoxLayout()
    row_hk.addWidget(QLabel("开始"))
    host.edit_cast_start = QKeySequenceEdit(
        QKeySequence(host._settings.cast_start_hotkey)
    )
    host.edit_cast_start.setMaximumSequenceLength(1)
    host.edit_cast_start.keySequenceChanged.connect(host._on_cast_start_hotkey_changed)
    row_hk.addWidget(host.edit_cast_start, 1)
    row_hk.addWidget(QLabel("结束"))
    host.edit_cast_stop = QKeySequenceEdit(
        QKeySequence(host._settings.cast_stop_hotkey)
    )
    host.edit_cast_stop.setMaximumSequenceLength(1)
    host.edit_cast_stop.keySequenceChanged.connect(host._on_cast_stop_hotkey_changed)
    row_hk.addWidget(host.edit_cast_stop, 1)
    batch_l.addLayout(row_hk)
    hk_tip = QLabel("全局快捷键（游戏占焦点时也可用）；默认 F8 开始、F9 结束")
    hk_tip.setWordWrap(True)
    hk_tip.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
    batch_l.addWidget(hk_tip)
    lay.addWidget(batch)

    wait = QGroupBox("拉漂成功后再抛 · 等待")
    wait_l = QVBoxLayout(wait)
    wait_l.setSpacing(8)
    wait_l.addWidget(QLabel("上下限（秒）· 夹到 0～30 · 拉漂结束后抽样等待再抛下一杆"))
    host.bar_cast_wait = SingleRangeBar(
        vmin=0.0,
        vmax=30.0,
        value=(s.cast_wait_lo_s, s.cast_wait_hi_s),
        unit="s",
        title="等待",
        min_span=0.0,
    )
    host.bar_cast_wait.rangeChanged.connect(host._on_cast_wait_changed)
    wait_l.addWidget(host.bar_cast_wait)
    lay.addWidget(wait)
    lay.addStretch(1)

    scroll.setWidget(inner)
    page_l.addWidget(scroll, 1)
    return page
