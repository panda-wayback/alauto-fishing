"""自动抛杆配置页：次数、快捷键、满蓄秒数、收竿等待区间、本页日志。"""

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
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.dual_range_axis import SingleRangeBar
from tools.shell_theme import TEXT_MUTED

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_cast_page(host: "PreviewApp") -> QWidget:
    page = QWidget()
    root = QVBoxLayout(page)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    split = QSplitter(Qt.Orientation.Vertical)
    split.setChildrenCollapsible(False)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 0, 4, 0)
    lay.setSpacing(8)

    tip = QLabel(
        "主控勾选「自动抛杆」(C) 后：光标旁认出水面漂再右键开始 / 再右键结束；"
        "F8 / F9 备用。蓄力：目标比例 × 满蓄秒数，再加约 ±0.2 秒抖动后松开。"
        "下一杆须等拉漂结束后再等待（默认 3 秒）。标定请用 make cast-calib。"
    )
    tip.setWordWrap(True)
    tip.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
    lay.addWidget(tip)

    batch = QGroupBox("本轮抛杆")
    batch_l = QVBoxLayout(batch)
    batch_l.setSpacing(8)
    row_n = QHBoxLayout()
    row_n.addWidget(QLabel("抛几次"))
    host.spin_cast_count = QSpinBox()
    host.spin_cast_count.setRange(1, 20)
    host.spin_cast_count.setValue(int(host._settings.cast_count))
    host.spin_cast_count.valueChanged.connect(host._on_cast_count_changed)
    row_n.addWidget(host.spin_cast_count)
    row_n.addStretch(1)
    batch_l.addLayout(row_n)

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
    wait_l.addWidget(QLabel("上下限（秒）· 夹到 0～30 · 拉漂结束后抽样等待再抛下一杆"))
    s = host._settings
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
    split.addWidget(scroll)

    log_wrap = QWidget()
    log_l = QVBoxLayout(log_wrap)
    log_l.setContentsMargins(0, 8, 0, 0)
    log_l.setSpacing(4)
    log_title = QLabel("抛杆配置日志")
    log_title.setObjectName("sectionTitle")
    log_l.addWidget(log_title)
    host.cast_log = QPlainTextEdit()
    host.cast_log.setObjectName("mainLog")
    host.cast_log.setReadOnly(True)
    host.cast_log.setMinimumHeight(100)
    host.cast_log.setPlaceholderText(
        "最新在上 · 第几次 · 按下秒数 · 拉漂后等待 · 快捷键…"
    )
    log_l.addWidget(host.cast_log, 1)
    split.addWidget(log_wrap)
    split.setStretchFactor(0, 3)
    split.setStretchFactor(1, 1)
    split.setSizes([420, 160])
    root.addWidget(split)
    return page
