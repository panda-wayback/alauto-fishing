"""主控页：A/B 开关、读数、状态日志。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.shell_theme import DANGER, TEXT_FAINT, TEXT_MUTED

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_main_page(host: "PreviewApp") -> QWidget:
    # —— 主控 ——
    page_main = QWidget()
    main_root = QVBoxLayout(page_main)
    main_root.setContentsMargins(0, 0, 0, 0)
    main_root.setSpacing(0)
    main_split = QSplitter(Qt.Orientation.Vertical)
    main_split.setChildrenCollapsible(False)
    
    main_top = QWidget()
    main_l = QVBoxLayout(main_top)
    main_l.setContentsMargins(0, 0, 0, 0)
    main_l.setSpacing(8)
    switches = QGroupBox("开关")
    sw = QVBoxLayout(switches)
    sw.setSpacing(8)
    host.chk_b = QCheckBox("自动拉漂")
    host.chk_b.setObjectName("switchRow")
    host.chk_b.setCursor(Qt.CursorShape.PointingHandCursor)
    host.chk_b.setToolTip("Decide + Act：有漂后按策略按住/松开")
    host.chk_b.toggled.connect(host._on_b_toggled)
    sw.addWidget(host.chk_b)
    host.chk_a = QCheckBox("声音开钓")
    host.chk_a.setObjectName("switchRow")
    host.chk_a.setCursor(Qt.CursorShape.PointingHandCursor)
    host.chk_a.setToolTip("听开钓水声 → 点第一下 → 等漂后交给自动拉漂")
    host.chk_a.toggled.connect(host._on_a_toggled)
    sw.addWidget(host.chk_a)
    host.btn_float = QPushButton("浮窗")
    host.btn_float.setObjectName("btnPrimary")
    host.btn_float.setCursor(Qt.CursorShape.PointingHandCursor)
    host.btn_float.setToolTip("同一窗口切到紧凑状态显示")
    host.btn_float.clicked.connect(lambda: host._set_compact_mode(True))
    sw.addWidget(host.btn_float)
    main_l.addWidget(switches)
    
    readout = QFrame()
    readout.setObjectName("readout")
    ro = QVBoxLayout(readout)
    ro.setContentsMargins(12, 10, 12, 10)
    ro.setSpacing(4)
    row1 = QHBoxLayout()
    row1.setSpacing(8)
    host.lbl_pos = QLabel("POS: 无漂")
    host.lbl_pos.setStyleSheet(
        f"font-size:16px; font-weight:700; color:{DANGER};"
    )
    row1.addWidget(host.lbl_pos)
    host.lbl_strat_detail = QLabel("")
    host.lbl_strat_detail.setStyleSheet(
        f"font-size:12px; color:{TEXT_MUTED};"
    )
    row1.addWidget(host.lbl_strat_detail, 1)
    host.lbl_perf = QLabel("")
    host.lbl_perf.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    row1.addWidget(host.lbl_perf)
    ro.addLayout(row1)
    host.lbl_session = QLabel("会话：—")
    host.lbl_session.setStyleSheet(f"font-size:12px; color:{TEXT_MUTED};")
    ro.addWidget(host.lbl_session)
    host.lbl_mouse = QLabel("意图 — · 程序 — · 系统 —")
    host.lbl_mouse.setStyleSheet(f"font-size:13px; font-weight:600; color:{TEXT_MUTED};")
    ro.addWidget(host.lbl_mouse)
    host.lbl_hint = QLabel("有 ROI 则持续监控；框选在「自动拉漂配置」")
    host.lbl_hint.setObjectName("hint")
    host.lbl_hint.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    ro.addWidget(host.lbl_hint)
    host.lbl_intent = QLabel("")
    host.lbl_intent.hide()
    host.lbl_mouse_diag = QLabel("")
    host.lbl_mouse_diag.setStyleSheet(f"color:{TEXT_MUTED};")
    host.lbl_mouse_diag.setWordWrap(True)
    ro.addWidget(host.lbl_mouse_diag)
    main_l.addWidget(readout)
    main_l.addStretch(1)
    main_split.addWidget(main_top)
    
    log_wrap = QWidget()
    log_l = QVBoxLayout(log_wrap)
    log_l.setContentsMargins(0, 8, 0, 0)
    log_l.setSpacing(4)
    log_title = QLabel("状态日志")
    log_title.setObjectName("sectionTitle")
    log_l.addWidget(log_title)
    host.log = QPlainTextEdit()
    host.log.setObjectName("mainLog")
    host.log.setReadOnly(True)
    host.log.setMinimumHeight(120)
    host.log.setPlaceholderText("最新在上 · 游戏开始/结束 · A/B · 声音触发…")
    log_l.addWidget(host.log, 1)
    main_split.addWidget(log_wrap)
    main_split.setStretchFactor(0, 1)
    main_split.setStretchFactor(1, 2)
    main_split.setSizes([180, 320])
    main_root.addWidget(main_split)

    return page_main
