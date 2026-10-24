"""主控页：A / B / C 三行能力卡（精简主读数）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.shell_log import PageLogPopup
from tools.shell_theme import BORDER

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def _sync_cap_active(card: QFrame, chk: QCheckBox) -> None:
    card.setProperty("active", "true" if chk.isChecked() else "false")
    style = card.style()
    style.unpolish(card)
    style.polish(card)
    card.update()


def _cap_card(*, chk: QCheckBox) -> tuple[QFrame, QHBoxLayout, QHBoxLayout]:
    """返回 (card, head_row, body_row)。body_row 用于横排主读数。"""
    card = QFrame()
    card.setObjectName("capabilityCard")
    root = QVBoxLayout(card)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    head = QFrame()
    head.setObjectName("capabilityHead")
    hl = QHBoxLayout(head)
    hl.setContentsMargins(10, 7, 10, 7)
    hl.setSpacing(8)
    chk.setObjectName("capSwitch")
    chk.setCursor(Qt.CursorShape.PointingHandCursor)
    hl.addWidget(chk, 0)
    hl.addStretch(1)
    root.addWidget(head)

    body = QWidget()
    body_l = QHBoxLayout(body)
    body_l.setContentsMargins(10, 8, 10, 10)
    body_l.setSpacing(10)
    body_l.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    root.addWidget(body)

    chk.toggled.connect(lambda _=False, c=card, k=chk: _sync_cap_active(c, k))
    _sync_cap_active(card, chk)
    return card, hl, body_l


def _hero_block(key: str, value: QLabel) -> QVBoxLayout:
    col = QVBoxLayout()
    col.setSpacing(2)
    col.setContentsMargins(0, 0, 0, 0)
    k = QLabel(key)
    k.setObjectName("capKey")
    col.addWidget(k)
    value.setObjectName("capValue")
    col.addWidget(value)
    return col


def build_main_page(host: "PreviewApp") -> QWidget:
    from common.license import load_license
    from datetime import datetime

    main_top = QWidget()
    main_l = QVBoxLayout(main_top)
    main_l.setContentsMargins(0, 0, 0, 0)
    main_l.setSpacing(6)

    host.lbl_license = QLabel("")
    host.lbl_license.setObjectName("licenseBanner")
    host.lbl_license.setAlignment(Qt.AlignmentFlag.AlignCenter)
    main_l.addWidget(host.lbl_license)

    def _set_license_tone(tone: str) -> None:
        """tone: '' | warn | danger — 临近到期用柔和琥珀，失效才用淡红。"""
        host.lbl_license.setProperty("warn", "true" if tone == "warn" else "false")
        host.lbl_license.setProperty(
            "danger", "true" if tone == "danger" else "false"
        )
        st = host.lbl_license.style()
        st.unpolish(host.lbl_license)
        st.polish(host.lbl_license)
        host.lbl_license.update()

    def _refresh_license_banner() -> None:
        lic = load_license()
        if lic is None:
            host.lbl_license.setText("未授权")
            host.lbl_license.setToolTip("")
            _set_license_tone("danger")
            return
        deadline = lic.expire_at
        secs = int((deadline - datetime.now()).total_seconds())
        host.lbl_license.setToolTip(
            f"到期：{deadline.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if secs <= 0:
            host.lbl_license.setText("授权已到期")
            _set_license_tone("danger")
            return
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, sec = divmod(rem, 60)
        host.lbl_license.setText(
            f"授权剩余 {days} 天 {hours:02d}:{mins:02d}:{sec:02d}"
        )
        _set_license_tone("warn" if secs <= 3 * 86400 else "")

    host._refresh_license_banner = _refresh_license_banner
    host._license_timer = QTimer(host)
    host._license_timer.timeout.connect(_refresh_license_banner)
    host._license_timer.start(1000)
    _refresh_license_banner()

    host.chk_a = QCheckBox("自动起勾")
    host.chk_a.setToolTip("A：听开钓水声 → 点第一下 → 等漂后交给自动拉线")
    host.chk_a.toggled.connect(host._on_a_toggled)

    host.chk_b = QCheckBox("自动拉线")
    host.chk_b.setToolTip("B：Decide + Act，有漂后按策略按住 / 松开")
    host.chk_b.toggled.connect(host._on_b_toggled)

    host.chk_c = QCheckBox("自动抛竿")
    host.chk_c.setToolTip("C：光标成漂形后右键开停；F8 / F9 备用。关则整模块停。")
    host.chk_c.toggled.connect(host._on_c_toggled)

    def _ghost(name: str) -> QLabel:
        lbl = QLabel("", main_top)
        lbl.setObjectName(name)
        lbl.hide()
        return lbl

    host.lbl_strat_detail = _ghost("stratDetail")
    host.lbl_perf = _ghost("perf")
    host.lbl_mouse = _ghost("mouse")
    host.lbl_mouse_diag = _ghost("mouseDiag")
    host.lbl_intent = _ghost("intent")
    host.lbl_a_meta = _ghost("aMeta")
    host.lbl_cast_hint = _ghost("castHint")

    caps = QVBoxLayout()
    caps.setSpacing(6)
    caps.setContentsMargins(0, 0, 0, 0)

    # —— A ——
    a_card, _a_head, a_body = _cap_card(chk=host.chk_a)
    host.lbl_session = QLabel("关")
    a_body.addLayout(_hero_block("会话", host.lbl_session), 0)
    a_body.addStretch(1)
    caps.addWidget(a_card)

    # —— B ——
    b_card, b_head, b_body = _cap_card(chk=host.chk_b)
    host.lbl_b_act = QLabel("—")
    host.lbl_b_act.setObjectName("capAct")
    host.lbl_b_act.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    b_head.addWidget(host.lbl_b_act, 0)
    host.lbl_pos = QLabel("—")
    host.lbl_pos.setObjectName("capValue")
    b_body.addLayout(_hero_block("POS", host.lbl_pos), 0)
    b_body.addStretch(1)
    caps.addWidget(b_card)

    # —— C ——
    c_card, _c_head, c_body = _cap_card(chk=host.chk_c)
    host.lbl_cast_remain = QLabel("—")
    host.lbl_cast_remain.setObjectName("castRemain")
    host.lbl_cast_remain.setToolTip("待命=配置次数；进行中=剩余/共")
    host.lbl_cast_remain_cap = QLabel("")
    host.lbl_cast_remain_cap.hide()
    c_body.addLayout(_hero_block("抛竿", host.lbl_cast_remain), 0)
    c_side = QVBoxLayout()
    c_side.setSpacing(2)
    host.lbl_cast = QLabel("关")
    host.lbl_cast.setObjectName("capMeta")
    c_side.addWidget(host.lbl_cast)
    c_side.addStretch(1)
    c_body.addLayout(c_side, 1)
    host.lbl_arm_preview = QLabel()
    host.lbl_arm_preview.setFixedSize(36, 36)
    host.lbl_arm_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_arm_preview.setToolTip("系统光标 · 绿=就绪 · 灰=等待")
    host.lbl_arm_preview.setStyleSheet(
        f"background:{BORDER}; border:2px solid {BORDER}; border-radius:6px;"
    )
    host.lbl_arm_preview.hide()
    c_body.addWidget(host.lbl_arm_preview, 0, Qt.AlignmentFlag.AlignVCenter)
    caps.addWidget(c_card)

    main_l.addLayout(caps)

    foot = QHBoxLayout()
    foot.setSpacing(8)
    host.lbl_hint = QLabel("")
    host.lbl_hint.setObjectName("hint")
    host.lbl_hint.setWordWrap(True)
    foot.addWidget(host.lbl_hint, 1)
    host._main_log_popup = PageLogPopup(
        host, "状态日志", object_name="mainLog", placeholder="最新在上…"
    )
    host.log = host._main_log_popup.editor
    foot.addWidget(host._main_log_popup.make_button(), 0)
    host.btn_float = QPushButton("浮窗")
    host.btn_float.setObjectName("btnFloat")
    host.btn_float.setCursor(Qt.CursorShape.PointingHandCursor)
    host.btn_float.setToolTip("同一窗口切到紧凑状态显示")
    host.btn_float.clicked.connect(lambda: host._set_compact_mode(True))
    foot.addWidget(host.btn_float, 0)
    main_l.addLayout(foot)

    page_main = QWidget()
    page_l = QVBoxLayout(page_main)
    page_l.setContentsMargins(0, 0, 0, 0)
    page_l.setSpacing(0)
    page_l.addWidget(main_top, 0)
    page_l.addStretch(1)
    return page_main
