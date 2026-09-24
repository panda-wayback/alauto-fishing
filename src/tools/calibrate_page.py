"""自动拉漂配置页：ROI / MONITOR / BAR / 策略。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.bar_mark_canvas import BarMarkCanvas
from tools.dual_range_axis import DualRangeAxis
from tools.image_canvas import ImageCanvas
from tools.shell_theme import TEXT_MUTED

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_calibrate_page(host: "PreviewApp") -> QWidget:
    # —— 自动拉漂配置（ROI / BAR / 策略 / 本页日志）——
    page_cal = QWidget()
    cal_root = QVBoxLayout(page_cal)
    cal_root.setContentsMargins(0, 0, 0, 0)
    cal_root.setSpacing(0)
    cal_split = QSplitter(Qt.Orientation.Vertical)
    cal_split.setChildrenCollapsible(False)
    
    cal_scroll = QScrollArea()
    cal_scroll.setWidgetResizable(True)
    cal_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    cal_inner = QWidget()
    cal_l = QVBoxLayout(cal_inner)
    cal_l.setContentsMargins(0, 0, 4, 0)
    vision = QGroupBox("画面 · ROI / MONITOR / BAR")
    vis = QVBoxLayout(vision)
    vis.setSpacing(8)
    row_mon = QHBoxLayout()
    host.btn_capture = QPushButton("截屏框选")
    host.btn_rebox = QPushButton("重框")
    host.btn_confirm = QPushButton("确认框选")
    host.btn_confirm.setObjectName("btnPrimary")
    host.btn_cancel = QPushButton("取消框选")
    host.btn_cancel.setObjectName("btnGhost")
    host.btn_roi_default = QPushButton("恢复默认框")
    host.btn_roi_default.setObjectName("btnGhost")
    host.btn_capture.clicked.connect(host._capture_fullscreen)
    host.btn_rebox.clicked.connect(host._load_screen_for_select)
    host.btn_confirm.clicked.connect(host._confirm_selection)
    host.btn_cancel.clicked.connect(host._cancel_selection)
    host.btn_roi_default.clicked.connect(host._restore_default_roi)
    for b in (
        host.btn_capture,
        host.btn_rebox,
        host.btn_confirm,
        host.btn_cancel,
        host.btn_roi_default,
    ):
        row_mon.addWidget(b)
    row_mon.addStretch(1)
    vis.addLayout(row_mon)
    host.monitor = ImageCanvas("MONITOR · 等待截屏")
    host.monitor.setMinimumHeight(180)
    vis.addWidget(host.monitor)
    bar_title = QHBoxLayout()
    bar_lbl = QLabel("BAR · 条界标记")
    bar_lbl.setObjectName("sectionTitle")
    bar_title.addWidget(bar_lbl)
    host.lbl_bar_hint = QLabel("蓝=程序 黄=手动")
    host.lbl_bar_hint.setStyleSheet(f"color:{TEXT_MUTED};")
    bar_title.addWidget(host.lbl_bar_hint, 1)
    host.btn_bar_refresh = QPushButton("刷新参考图")
    host.btn_bar_refresh.setToolTip(
        "点击后等待下一次鱼漂识别成功，用该帧更新条界参考图"
    )
    host.btn_bar_refresh.clicked.connect(host._refresh_bar_ref)
    bar_title.addWidget(host.btn_bar_refresh)
    host.btn_bar_clear = QPushButton("清除我的标记")
    host.btn_bar_clear.setObjectName("btnGhost")
    host.btn_bar_clear.clicked.connect(host._clear_manual_bar)
    bar_title.addWidget(host.btn_bar_clear)
    vis.addLayout(bar_title)
    host.bar_canvas = BarMarkCanvas()
    host.bar_canvas.setMinimumHeight(140)
    host.bar_canvas.manual_changed.connect(host._on_manual_bar_changed)
    vis.addWidget(host.bar_canvas)
    cal_l.addWidget(vision)
    
    strat = QGroupBox("拉漂策略")
    strat_l = QVBoxLayout(strat)
    row_pol = QHBoxLayout()
    host.btn_apply_policy = QPushButton("应用策略")
    host.btn_apply_policy.setObjectName("btnPrimary")
    host.btn_apply_policy.clicked.connect(host._apply_policy)
    row_pol.addWidget(host.btn_apply_policy)
    row_pol.addStretch(1)
    strat_l.addLayout(row_pol)
    strat_l.addWidget(QLabel("拖动数轴 · 两段不重叠且间隔≥1 · 精度0.1"))
    s = host._settings
    host.range_axis = DualRangeAxis(
        press=(s.press_lo, s.press_hi),
        release=(s.release_lo, s.release_hi),
        min_gap=1.0,
    )
    host.range_axis.rangesChanged.connect(host._on_ranges_changed)
    strat_l.addWidget(host.range_axis)
    row_gap = QHBoxLayout()
    row_gap.addWidget(QLabel("按下间隔"))
    host.sld_press_interval = QSlider(Qt.Orientation.Horizontal)
    host.sld_press_interval.setRange(0, 300)
    host.sld_press_interval.setSingleStep(10)
    host.sld_press_interval.setPageStep(50)
    host.sld_press_interval.setValue(int(round(s.press_interval_s * 1000)))
    host.sld_press_interval.setToolTip("两次程序按下的最短间隔；松开立刻")
    host.sld_press_interval.valueChanged.connect(host._on_press_interval_changed)
    host.sld_press_interval.sliderReleased.connect(host._on_press_interval_released)
    row_gap.addWidget(host.sld_press_interval, 1)
    host.lbl_press_interval = QLabel(f"{s.press_interval_s:.2f}s")
    host.lbl_press_interval.setMinimumWidth(48)
    row_gap.addWidget(host.lbl_press_interval)
    row_gap.addWidget(QLabel("（0～0.3s）"))
    strat_l.addLayout(row_gap)
    cal_l.addWidget(strat)
    cal_l.addStretch(1)
    cal_scroll.setWidget(cal_inner)
    cal_split.addWidget(cal_scroll)
    
    cal_log_wrap = QWidget()
    cal_log_l = QVBoxLayout(cal_log_wrap)
    cal_log_l.setContentsMargins(0, 4, 0, 0)
    cal_log_l.setSpacing(2)
    cal_log_title = QLabel("本页日志（开始/结束拉漂 · 最新在上）")
    cal_log_title.setObjectName("sectionTitle")
    cal_log_l.addWidget(cal_log_title)
    host.cal_log = QPlainTextEdit()
    host.cal_log.setObjectName("calLog")
    host.cal_log.setReadOnly(True)
    host.cal_log.setMinimumHeight(100)
    host.cal_log.setPlaceholderText("开始拉漂 / 结束拉漂 / ROI…")
    cal_log_l.addWidget(host.cal_log, 1)
    cal_split.addWidget(cal_log_wrap)
    cal_split.setStretchFactor(0, 3)
    cal_split.setStretchFactor(1, 2)
    cal_split.setSizes([420, 180])
    cal_root.addWidget(cal_split)

    return page_cal
