"""激活密钥对话框。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from common.license import activate_key, is_licensed, load_license


class LicenseDialog(QDialog):
    """返回 Accepted 表示已有有效 license；Rejected 表示用户放弃。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("激活")
        self.setModal(True)
        self.setMinimumWidth(420)

        tip = QLabel("本软件需要激活密钥才能使用。请输入密钥：")
        tip.setWordWrap(True)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("ALBN1....")
        self._edit.returnPressed.connect(self._on_activate)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        info = load_license()
        if info is not None and not info.is_valid():
            self._status.setText(
                f"授权已于 {info.expire_on.isoformat()} 到期，请输入新密钥。"
            )

        btn_ok = QPushButton("激活")
        btn_ok.clicked.connect(self._on_activate)
        btn_quit = QPushButton("退出")
        btn_quit.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn_quit)
        row.addWidget(btn_ok)

        lay = QVBoxLayout(self)
        lay.addWidget(tip)
        lay.addWidget(self._edit)
        lay.addWidget(self._status)
        lay.addLayout(row)

    def _on_activate(self) -> None:
        text = self._edit.text().strip()
        if not text:
            self._status.setText("请输入密钥。")
            return
        try:
            info = activate_key(text)
        except ValueError as exc:
            self._status.setText(str(exc))
            return
        QMessageBox.information(
            self,
            "激活成功",
            f"已激活 {info.days} 天，有效期至 {info.expire_on.isoformat()}。",
        )
        self.accept()


def ensure_licensed() -> bool:
    """已授权返回 True；弹出激活框，成功 True，取消 False。"""
    if is_licensed():
        return True
    dlg = LicenseDialog()
    return dlg.exec() == QDialog.DialogCode.Accepted and is_licensed()
