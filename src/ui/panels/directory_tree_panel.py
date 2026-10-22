# === 文件路径: src/ui/panels/directory_tree_panel.py ===
"""目录树面板：本地目录浏览，可把选中目录设为扫描目标。

通过信号与主窗口解耦（面板之间不直接互引）。
"""
from __future__ import annotations

from PySide6.QtCore import QDir, Signal
from PySide6.QtWidgets import (
    QFileSystemModel, QHBoxLayout, QLabel, QPushButton, QTreeView, QVBoxLayout, QWidget,
)


class DirectoryTreePanel(QWidget):
    path_selected = Signal(str)    # 选中目录（更新扫描目标）
    scan_requested = Signal(str)   # 立即扫描该目录

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        hint = QLabel("双击目录可设为扫描目标")
        hint.setProperty("role", "muted")
        layout.addWidget(hint)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot)
        self.model.setReadOnly(True)

        self.view = QTreeView(self)
        self.view.setModel(self.model)
        self.view.setHeaderHidden(True)
        for col in range(1, self.model.columnCount()):
            self.view.hideColumn(col)
        self.view.setAnimated(True)
        self.view.setIndentation(14)
        self.view.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.view, 1)

        btn_row = QHBoxLayout()
        self.btn_scan = QPushButton("开始扫描")
        self.btn_scan.setObjectName("primaryButton")
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        btn_row.addWidget(self.btn_scan)
        layout.addLayout(btn_row)

    def current_path(self) -> str:
        index = self.view.currentIndex()
        if not index.isValid():
            return ""
        return self.model.filePath(index)

    def current_dir(self) -> str:
        """若选中项是文件则返回其目录，否则返回自身路径。"""
        path = self.current_path()
        return path

    def _on_double_clicked(self, index) -> None:
        path = self.model.filePath(index)
        if path:
            self.path_selected.emit(path)

    def _on_scan_clicked(self) -> None:
        path = self.current_dir()
        if path:
            self.scan_requested.emit(path)

    def select_path(self, path: str) -> None:
        index = self.model.index(path)
        if index.isValid():
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)

    def refresh_icons(self) -> None:  # 与其他面板保持统一接口
        return
