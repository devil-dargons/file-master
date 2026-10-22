# === 文件路径: src/ui/panels/task_output_panel.py ===
"""任务输出面板：扫描/缩略图/文件操作的后台日志流。"""
from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)


class TaskOutputPanel(QWidget):
    MAX_BLOCKS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(self.MAX_BLOCKS)
        self.text.setPlaceholderText("后台任务日志将显示在这里…")
        layout.addWidget(self.text, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self.text.clear)
        row.addWidget(self.btn_clear)
        layout.addLayout(row)

    def append_message(self, message: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        prefix = {"error": "[错误]", "warn": "[警告]"}.get(level, "[信息]")
        self.text.appendPlainText(f"{stamp} {prefix} {message}")

    def refresh_icons(self) -> None:
        return
