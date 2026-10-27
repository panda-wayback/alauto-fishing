"""更多页：恢复默认、打包默认（权限 / 置顶已移到主控页底部）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.shell_config import is_frozen_app
from tools.shell_theme import TEXT_MUTED

from common.expire import load_expire_on

if TYPE_CHECKING:
    from tools.preview_app import PreviewApp


def build_more_page(host: "PreviewApp") -> QWidget:
    # —— 更多：恢复默认 / 打包默认 ——
    page_more = QWidget()
    more_scroll = QScrollArea()
    more_scroll.setWidgetResizable(True)
    more_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    more_inner = QWidget()
    more_l = QVBoxLayout(more_inner)
    more_l.setContentsMargins(0, 0, 4, 0)
    more_l.setSpacing(8)

    pkg_on = load_expire_on()
    if pkg_on is not None:
        validity = QGroupBox("有效期")
        validity_l = QVBoxLayout(validity)
        lbl_pkg = QLabel(f"本安装包到期 {pkg_on.isoformat()}")
        validity_l.addWidget(lbl_pkg)
        more_l.addWidget(validity)

    restore = QGroupBox("恢复默认")
    restore_l = QVBoxLayout(restore)
    hint_restore = QLabel(
        "把拉线、起勾、抛竿和截图范围恢复为默认，并清空手动条界；"
        "不删除模板、录音和授权"
    )
    hint_restore.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
    hint_restore.setWordWrap(True)
    restore_l.addWidget(hint_restore)
    host.btn_restore_defaults = QPushButton("恢复默认")
    host.btn_restore_defaults.setObjectName("btnGhost")
    host.btn_restore_defaults.setToolTip(
        "恢复打包默认（没有则用内建缺省），并按当前主屏重算截图框"
    )
    host.btn_restore_defaults.clicked.connect(host._on_restore_defaults)
    restore_l.addWidget(host.btn_restore_defaults)
    more_l.addWidget(restore)

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
