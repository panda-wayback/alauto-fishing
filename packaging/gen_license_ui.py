#!/usr/bin/env python3
"""密钥生成小窗：7/30 天、批量、列表可复制。

用法（仓库根）:
  PYTHONPATH=src python packaging/gen_license_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from common.license import issue_key  # noqa: E402


class GenLicenseWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("生成激活密钥")
        self.resize(560, 420)

        self._opt_7 = QRadioButton("7 天")
        self._opt_30 = QRadioButton("30 天")
        self._opt_30.setChecked(True)
        days_row = QHBoxLayout()
        days_row.addWidget(QLabel("天数："))
        days_row.addWidget(self._opt_7)
        days_row.addWidget(self._opt_30)
        days_row.addStretch(1)

        self._count = QSpinBox()
        self._count.setRange(1, 200)
        self._count.setValue(1)
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("数量："))
        count_row.addWidget(self._count)
        count_row.addStretch(1)

        btn_gen = QPushButton("生成")
        btn_gen.setDefault(True)
        btn_gen.clicked.connect(self._on_generate)
        btn_copy = QPushButton("复制全部")
        btn_copy.clicked.connect(self._on_copy_all)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._on_clear)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_gen)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)

        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setPlaceholderText("生成的密钥会显示在这里，一行一个，可全选复制。")
        self._out.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        tip = QLabel("仅本机发密钥用；勿打进用户安装包。")
        tip.setStyleSheet("color:#666;")

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(days_row)
        lay.addLayout(count_row)
        lay.addLayout(btn_row)
        lay.addWidget(self._out, 1)
        lay.addWidget(tip)
        self.setCentralWidget(root)

    def _days(self) -> int:
        return 7 if self._opt_7.isChecked() else 30

    def _on_generate(self) -> None:
        n = int(self._count.value())
        days = self._days()
        lines = [issue_key(days) for _ in range(n)]
        existing = self._out.toPlainText().rstrip()
        block = "\n".join(lines)
        if existing:
            self._out.setPlainText(existing + "\n" + block)
        else:
            self._out.setPlainText(block)
        # 选中刚生成的部分，方便立刻复制
        cursor = self._out.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._out.setTextCursor(cursor)

    def _on_copy_all(self) -> None:
        text = self._out.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "复制", "列表为空。")
            return
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "复制", f"已复制 {len(text.splitlines())} 条。")

    def _on_clear(self) -> None:
        self._out.clear()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = GenLicenseWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
