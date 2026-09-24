"""更多页：权限、开钓第一下区间、打包默认。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.dual_range_axis import SingleRangeBar
from tools.shell_config import is_frozen_app
from tools.shell_theme import TEXT_MUTED

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_more_page(host: "PreviewApp") -> QWidget:
    s = host._settings
    # —— 更多：权限 ——
    page_more = QWidget()
    more_scroll = QScrollArea()
    more_scroll.setWidgetResizable(True)
    more_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    more_inner = QWidget()
    more_l = QVBoxLayout(more_inner)
    more_l.setContentsMargins(0, 0, 4, 0)
    more_l.setSpacing(8)
    
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
    more_l.addWidget(perm)
    
    click = QGroupBox("开钓第一下")
    click_l = QVBoxLayout(click)
    hint_click = QLabel(
        "命中水声后：等待 → 长按 → 松开 → 再停顿；拖端点或整段，区间内均匀随机"
    )
    hint_click.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
    hint_click.setWordWrap(True)
    click_l.addWidget(hint_click)
    host.bar_delay = SingleRangeBar(
        title="等待",
        vmin=0.0,
        vmax=5.0,
        value=(float(s.click_delay_lo_s), float(s.click_delay_hi_s)),
        unit="s",
        min_span=0.1,
    )
    host.bar_delay.rangeChanged.connect(host._on_click_timing_changed)
    click_l.addWidget(host.bar_delay)
    host.bar_hold = SingleRangeBar(
        title="长按",
        vmin=0.0,
        vmax=5.0,
        value=(float(s.click_hold_lo_s), float(s.click_hold_hi_s)),
        unit="s",
        min_span=0.1,
    )
    host.bar_hold.rangeChanged.connect(host._on_click_timing_changed)
    click_l.addWidget(host.bar_hold)
    host.bar_after = SingleRangeBar(
        title="松开后",
        vmin=0.0,
        vmax=5.0,
        value=(float(s.click_after_lo_s), float(s.click_after_hi_s)),
        unit="s",
        min_span=0.1,
    )
    host.bar_after.rangeChanged.connect(host._on_click_timing_changed)
    click_l.addWidget(host.bar_after)
    more_l.addWidget(click)
    
    if not is_frozen_app():
        pack = QGroupBox("打包默认")
        pack_l = QVBoxLayout(pack)
        hint_pack = QLabel(
            "把当前玩法配置写入 assets/shell_settings.json，提交后直接打包即可；"
            "不含窗位置/设备名等本机项"
        )
        hint_pack.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        hint_pack.setWordWrap(True)
        pack_l.addWidget(hint_pack)
        host.btn_save_bundled = QPushButton("写入打包默认")
        host.btn_save_bundled.setObjectName("btnPrimary")
        host.btn_save_bundled.setToolTip(
            "仅源码运行可用；写入仓库 assets/shell_settings.json"
        )
        host.btn_save_bundled.clicked.connect(host._on_save_bundled_defaults)
        pack_l.addWidget(host.btn_save_bundled)
        more_l.addWidget(pack)
    
    more_l.addStretch(1)
    more_scroll.setWidget(more_inner)
    more_page_l = QVBoxLayout(page_more)
    more_page_l.setContentsMargins(0, 0, 0, 0)
    more_page_l.addWidget(more_scroll)

    return page_more
