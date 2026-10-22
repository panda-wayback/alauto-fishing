"""主控页：A/B 开关、读数、状态日志。"""

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


def build_main_page(host: "PreviewApp") -> QWidget:
    from common.license import load_license
    from datetime import datetime

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
        # 不足 3 天提醒
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
    host.chk_c.setToolTip(
        "开：光标旁认漂后右键开始 / 再右键结束；F8 / F9 备用。"
        "关：不认漂、不响应右键与快捷键。"
    )
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
    cast_row = QHBoxLayout()
    cast_row.setSpacing(10)
    cast_txt = QVBoxLayout()
    cast_txt.setSpacing(2)
    host.lbl_cast = QLabel("抛杆门闩：—")
    host.lbl_cast.setStyleSheet(f"font-size:12px; color:{TEXT_MUTED};")
    cast_txt.addWidget(host.lbl_cast)
    host.lbl_cast_hint = QLabel("与上方 POS（拉漂大框）无关")
    host.lbl_cast_hint.setStyleSheet(f"font-size:10px; color:{TEXT_FAINT};")
    cast_txt.addWidget(host.lbl_cast_hint)
    cast_row.addLayout(cast_txt, 1)
    host.lbl_arm_preview = QLabel()
    host.lbl_arm_preview.setFixedSize(72, 72)
    host.lbl_arm_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_arm_preview.setToolTip(
        "系统当前光标外形（mss 截不到）· 鼠标请停在游戏上 · 绿框=可开抛 · 灰框=未认漂"
    )
    host.lbl_arm_preview.setStyleSheet(
        f"background:{BORDER}; border:2px solid {BORDER}; border-radius:4px;"
    )
    host.lbl_arm_preview.hide()
    cast_row.addWidget(host.lbl_arm_preview, 0, Qt.AlignmentFlag.AlignTop)
    ro.addLayout(cast_row)
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
