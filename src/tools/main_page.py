"""主控页：A/B/C 开关、仪表盘三卡、状态日志。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.shell_theme import (
    ACCENT,
    ACCENT_DIM,
    BORDER,
    DANGER,
    TEXT_FAINT,
    TEXT_MUTED,
)

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp

_STYLE_OK = (
    f"font-size:11px; font-weight:700; color:{ACCENT}; "
    f"padding:5px 8px; border:1px solid {ACCENT_DIM}; border-radius:4px; "
    f"background-color: rgba(61,184,160,0.12);"
)
_STYLE_WARN = (
    f"font-size:11px; font-weight:700; color:{DANGER}; "
    f"padding:5px 8px; border:1px solid {DANGER}; border-radius:4px; "
    f"background-color: rgba(217,107,107,0.12);"
)


def _make_card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("statusCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    return card, lay


def _metric_cell(title: str) -> tuple[QFrame, QLabel]:
    cell = QFrame()
    cell.setObjectName("metricCell")
    cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    v = QVBoxLayout(cell)
    v.setContentsMargins(8, 6, 8, 6)
    v.setSpacing(2)
    val = QLabel("—")
    val.setAlignment(Qt.AlignmentFlag.AlignCenter)
    val.setStyleSheet(f"font-size:15px; font-weight:700; color:{TEXT_MUTED};")
    cap = QLabel(title)
    cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cap.setStyleSheet(f"font-size:10px; color:{TEXT_FAINT};")
    v.addWidget(val)
    v.addWidget(cap)
    return cell, val


def build_main_page(host: "PreviewApp") -> QWidget:
    from common.license import load_license
    from datetime import datetime

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

    host.lbl_license = QLabel("")
    host.lbl_license.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_license.setStyleSheet(_STYLE_OK)
    main_l.addWidget(host.lbl_license)

    def _refresh_license_banner() -> None:
        lic = load_license()
        if lic is None:
            host.lbl_license.setText("未授权")
            host.lbl_license.setToolTip("")
            host.lbl_license.setStyleSheet(_STYLE_WARN)
            return
        deadline = lic.expire_at
        secs = int((deadline - datetime.now()).total_seconds())
        host.lbl_license.setToolTip(
            f"到期：{deadline.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if secs <= 0:
            host.lbl_license.setText("授权已到期")
            host.lbl_license.setStyleSheet(_STYLE_WARN)
            return
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, sec = divmod(rem, 60)
        host.lbl_license.setText(
            f"授权剩余 {days} 天 {hours:02d}:{mins:02d}:{sec:02d}"
        )
        host.lbl_license.setStyleSheet(_STYLE_WARN if secs <= 3 * 86400 else _STYLE_OK)

    host._refresh_license_banner = _refresh_license_banner
    host._license_timer = QTimer(host)
    host._license_timer.timeout.connect(_refresh_license_banner)
    host._license_timer.start(1000)
    _refresh_license_banner()

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
    host.chk_c = QCheckBox("自动抛杆")
    host.chk_c.setObjectName("switchRow")
    host.chk_c.setCursor(Qt.CursorShape.PointingHandCursor)
    host.chk_c.setToolTip("开：光标成漂形后右键开停；F8 / F9 备用。关：整模块停。")
    host.chk_c.toggled.connect(host._on_c_toggled)
    sw.addWidget(host.chk_c)
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
    ro.setContentsMargins(0, 0, 0, 0)
    ro.setSpacing(8)

    # —— POS ——
    pos_card, pos_l = _make_card()
    pos_head = QHBoxLayout()
    pos_head.setSpacing(8)
    pos_title = QLabel("POS")
    pos_title.setObjectName("statusCardTitle")
    pos_head.addWidget(pos_title)
    pos_head.addStretch(1)
    host.lbl_perf = QLabel("")
    host.lbl_perf.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    pos_head.addWidget(host.lbl_perf)
    pos_l.addLayout(pos_head)
    pos_row = QHBoxLayout()
    pos_row.setSpacing(12)
    host.lbl_pos = QLabel("—")
    host.lbl_pos.setStyleSheet(f"font-size:26px; font-weight:700; color:{DANGER};")
    pos_row.addWidget(host.lbl_pos)
    right = QVBoxLayout()
    right.setSpacing(2)
    host.lbl_strat_detail = QLabel("")
    host.lbl_strat_detail.setStyleSheet(f"font-size:12px; color:{TEXT_MUTED};")
    right.addWidget(host.lbl_strat_detail)
    host.lbl_session = QLabel("")
    host.lbl_session.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    right.addWidget(host.lbl_session)
    right.addStretch(1)
    pos_row.addLayout(right, 1)
    pos_l.addLayout(pos_row)
    ro.addWidget(pos_card)

    # —— 抛杆 ——
    cast_card, cast_l = _make_card()
    cast_head = QHBoxLayout()
    cast_title = QLabel("抛杆")
    cast_title.setObjectName("statusCardTitle")
    cast_head.addWidget(cast_title)
    cast_head.addStretch(1)
    host.lbl_cast_hint = QLabel("")
    host.lbl_cast_hint.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    cast_head.addWidget(host.lbl_cast_hint)
    cast_l.addLayout(cast_head)
    cast_row = QHBoxLayout()
    cast_row.setSpacing(14)
    rem_wrap = QFrame()
    rem_wrap.setObjectName("metricCell")
    rem_wrap.setFixedWidth(72)
    rem_v = QVBoxLayout(rem_wrap)
    rem_v.setContentsMargins(6, 4, 6, 4)
    rem_v.setSpacing(0)
    host.lbl_cast_remain = QLabel("—")
    host.lbl_cast_remain.setObjectName("castRemain")
    host.lbl_cast_remain.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_cast_remain.setToolTip("待命=配置次数；进行中=剩余/共")
    rem_v.addWidget(host.lbl_cast_remain)
    host.lbl_cast_remain_cap = QLabel("次数")
    host.lbl_cast_remain_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_cast_remain_cap.setStyleSheet(f"font-size:10px; color:{TEXT_FAINT};")
    rem_v.addWidget(host.lbl_cast_remain_cap)
    cast_row.addWidget(rem_wrap)
    host.lbl_cast = QLabel("关")
    host.lbl_cast.setStyleSheet(f"font-size:18px; font-weight:700; color:{TEXT_MUTED};")
    host.lbl_cast.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    cast_row.addWidget(host.lbl_cast, 1)
    host.lbl_arm_preview = QLabel()
    host.lbl_arm_preview.setFixedSize(56, 56)
    host.lbl_arm_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_arm_preview.setToolTip("系统光标 · 绿=就绪 · 灰=等待")
    host.lbl_arm_preview.setStyleSheet(
        f"background:{BORDER}; border:2px solid {BORDER}; border-radius:6px;"
    )
    host.lbl_arm_preview.hide()
    cast_row.addWidget(host.lbl_arm_preview, 0, Qt.AlignmentFlag.AlignVCenter)
    cast_l.addLayout(cast_row)
    ro.addWidget(cast_card)

    # —— 鼠标 ——
    mouse_card, mouse_l = _make_card()
    mouse_head = QHBoxLayout()
    mouse_title = QLabel("鼠标")
    mouse_title.setObjectName("statusCardTitle")
    mouse_head.addWidget(mouse_title)
    mouse_head.addStretch(1)
    mouse_l.addLayout(mouse_head)
    metrics = QHBoxLayout()
    metrics.setSpacing(6)
    intent_cell, host.lbl_mouse_intent = _metric_cell("意图")
    prog_cell, host.lbl_mouse_prog = _metric_cell("程序")
    sys_cell, host.lbl_mouse_sys = _metric_cell("系统")
    metrics.addWidget(intent_cell)
    metrics.addWidget(prog_cell)
    metrics.addWidget(sys_cell)
    mouse_l.addLayout(metrics)
    # 兼容旧字段：单行汇总隐藏，诊断仅异常时显示
    host.lbl_mouse = QLabel("")
    host.lbl_mouse.hide()
    host.lbl_mouse_diag = QLabel("")
    host.lbl_mouse_diag.setStyleSheet(f"color:{DANGER}; font-size:11px;")
    host.lbl_mouse_diag.setWordWrap(True)
    host.lbl_mouse_diag.hide()
    mouse_l.addWidget(host.lbl_mouse_diag)
    host.lbl_intent = QLabel("")
    host.lbl_intent.hide()
    ro.addWidget(mouse_card)

    host.lbl_hint = QLabel("")
    host.lbl_hint.setObjectName("hint")
    host.lbl_hint.setStyleSheet(f"font-size:11px; color:{TEXT_FAINT};")
    host.lbl_hint.setWordWrap(True)
    ro.addWidget(host.lbl_hint)

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
    host.log.setPlaceholderText("最新在上…")
    log_l.addWidget(host.log, 1)
    main_split.addWidget(log_wrap)
    main_split.setStretchFactor(0, 1)
    main_split.setStretchFactor(1, 2)
    main_split.setSizes([240, 280])
    main_root.addWidget(main_split)

    return page_main
