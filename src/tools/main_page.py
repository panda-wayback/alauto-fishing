"""主控页：拉线主卡 + 起勾 / 抛竿并排次卡 + 底部权限栏。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
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
    for lbl in card.findChildren(QLabel):
        style.unpolish(lbl)
        style.polish(lbl)
    card.update()


def _make_card(chk: QCheckBox, *, hero: bool) -> tuple[QFrame, QHBoxLayout, QVBoxLayout]:
    """返回 (card, 顶栏, 卡身)。顶栏放勾选，动作字可加在顶栏右侧。"""
    card = QFrame()
    card.setObjectName("capabilityHero" if hero else "capabilityCard")
    root = QVBoxLayout(card)
    if hero:
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(6)
    else:
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

    head = QHBoxLayout()
    head.setSpacing(8)
    head.setContentsMargins(0, 0, 0, 0)
    chk.setObjectName("capSwitch")
    chk.setCursor(Qt.CursorShape.PointingHandCursor)
    head.addWidget(chk, 0)
    head.addStretch(1)
    root.addLayout(head)

    body = QVBoxLayout()
    body.setSpacing(2)
    body.setContentsMargins(0, 0, 0, 0)
    root.addLayout(body)

    chk.toggled.connect(lambda _=False, c=card, k=chk: _sync_cap_active(c, k))
    _sync_cap_active(card, chk)
    return card, head, body


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
    caps.setSpacing(10)
    caps.setContentsMargins(0, 0, 0, 0)

    # —— B 主卡：拉线 ——
    b_card, b_head, b_body = _make_card(host.chk_b, hero=True)
    host.lbl_b_act = QLabel("—")
    host.lbl_b_act.setObjectName("capAct")
    host.lbl_b_act.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    b_head.addWidget(host.lbl_b_act, 0)
    host.lbl_pos = QLabel("—")
    host.lbl_pos.setObjectName("heroPos")
    host.lbl_pos.setProperty("tone", "faint")
    b_body.addWidget(host.lbl_pos)
    pos_k = QLabel("POS")
    pos_k.setObjectName("capKey")
    b_body.addWidget(pos_k)
    caps.addWidget(b_card)

    # —— A / C 次卡 ——
    a_card, _a_head, a_body = _make_card(host.chk_a, hero=False)
    host.lbl_session = QLabel("关")
    host.lbl_session.setObjectName("capValue")
    a_body.addWidget(host.lbl_session)
    a_body.addStretch(1)

    c_card, c_head, c_body = _make_card(host.chk_c, hero=False)
    host.card_cast = c_card
    host.lbl_cast_badge = QLabel("待命")
    host.lbl_cast_badge.setObjectName("castBadge")
    host.lbl_cast_badge.setProperty("live", "false")
    host.lbl_cast_badge.hide()
    c_head.addWidget(host.lbl_cast_badge, 0)
    host.lbl_cast_remain = QLabel("—")
    host.lbl_cast_remain.setObjectName("castRemain")
    host.lbl_cast_remain.setProperty("tone", "faint")
    host.lbl_cast_remain.setToolTip("待命=配置次数；进行中=剩余/共")
    host.lbl_cast_remain_cap = QLabel("")
    host.lbl_cast_remain_cap.hide()
    c_row = QHBoxLayout()
    c_row.setSpacing(8)
    c_row.setContentsMargins(0, 4, 0, 0)
    c_row.addWidget(host.lbl_cast_remain, 0, Qt.AlignmentFlag.AlignVCenter)
    c_row.addStretch(1)
    host.lbl_arm_preview = QLabel()
    host.lbl_arm_preview.setFixedSize(36, 36)
    host.lbl_arm_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.lbl_arm_preview.setToolTip("系统光标 · 绿=就绪 · 灰=等待")
    host.lbl_arm_preview.setStyleSheet(
        f"background:{BORDER}; border:2px solid {BORDER}; border-radius:6px;"
    )
    host.lbl_arm_preview.hide()
    c_row.addWidget(host.lbl_arm_preview, 0, Qt.AlignmentFlag.AlignVCenter)
    c_body.addLayout(c_row)
    host.lbl_cast = QLabel("关")
    host.lbl_cast.setObjectName("capMeta")
    host.lbl_cast.setProperty("tone", "faint")
    c_body.addWidget(host.lbl_cast)
    host.lbl_cast_note = QLabel("")
    host.lbl_cast_note.setObjectName("castNote")
    host.lbl_cast_note.hide()
    c_body.addWidget(host.lbl_cast_note)

    pair = QHBoxLayout()
    pair.setSpacing(10)
    pair.setContentsMargins(0, 0, 0, 0)
    pair.addWidget(a_card, 1)
    pair.addWidget(c_card, 1)
    caps.addLayout(pair)

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

    # —— 底部权限栏：置顶 + 屏幕录制 / 控鼠（或以管理员重启）——
    # 放在主控最下方，启动即可直接操作，不必切到「更多」页
    perm = QGroupBox("权限")
    perm_l = QVBoxLayout(perm)
    host.chk_stay_on_top = QCheckBox("置顶")
    host.chk_stay_on_top.setChecked(bool(host._settings.stay_on_top))
    host.chk_stay_on_top.setToolTip("勾选后本窗始终在最上层")
    host.chk_stay_on_top.toggled.connect(host._on_stay_on_top_toggled)
    perm_l.addWidget(host.chk_stay_on_top)
    host.lbl_perm_screen = QLabel("屏幕…")
    perm_l.addWidget(host.lbl_perm_screen)
    host.btn_perm_screen = QPushButton("授权屏幕")
    host.btn_perm_screen.clicked.connect(host._on_perm_screen)
    perm_l.addWidget(host.btn_perm_screen)
    host.lbl_perm_input = QLabel("控鼠…")
    perm_l.addWidget(host.lbl_perm_input)
    host.btn_perm_input = QPushButton("授权控鼠")
    host.btn_perm_input.clicked.connect(host._on_perm_input)
    perm_l.addWidget(host.btn_perm_input)
    row_perm = QHBoxLayout()
    host.btn_perm_refresh = QPushButton("刷新")
    host.btn_perm_refresh.clicked.connect(host._refresh_permissions)
    row_perm.addWidget(host.btn_perm_refresh)
    host.btn_perm_reset = QPushButton("清理授权")
    host.btn_perm_reset.setToolTip(
        "清除本应用屏幕录制/辅助功能记录并打开系统设置（仅 macOS）"
    )
    host.btn_perm_reset.clicked.connect(host._on_perm_reset)
    host.btn_perm_reset.setVisible(sys.platform == "darwin")
    row_perm.addWidget(host.btn_perm_reset)
    row_perm.addStretch(1)
    perm_l.addLayout(row_perm)
    main_l.addWidget(perm)

    page_main = QWidget()
    page_l = QVBoxLayout(page_main)
    page_l.setContentsMargins(0, 0, 0, 0)
    page_l.setSpacing(0)
    page_l.addWidget(main_top, 0)
    page_l.addStretch(1)
    return page_main
