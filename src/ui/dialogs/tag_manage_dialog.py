from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
)
from src.db.dao import TagDAO
from src.ui.widgets.tag_editor_widget import TagEditorWidget


class TagManageDialog(QDialog):
    """
    标签管理弹窗：支持勾选现有标签 + 输入新标签。
    内容区复用 TagEditorWidget（与 ImageViewer 底部抽拉面板共用同一实现）。
    """
    def __init__(self, file_name: str, file_id: int, tag_dao: TagDAO, parent=None):
        super().__init__(parent)
        self.file_name = file_name
        self.file_id = file_id
        self.tag_dao = tag_dao

        self.setWindowTitle(f"管理标签: {file_name}")
        self.setMinimumWidth(350)
        self.setMinimumHeight(400)
        self._init_ui()
        self.editor.load_for_file(file_id)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 编辑区（复选标签列表 + 新标签输入）
        layout.addWidget(QLabel("勾选已有标签，或在下方输入新标签（多个用英文逗号分隔）:"))
        self.editor = TagEditorWidget(self.tag_dao, self)
        layout.addWidget(self.editor, 1)  # 占据主要空间

        # 2. 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton("确定")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 15px;")

        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def get_tags_to_add(self) -> list[str]:
        """获取最终需要添加的标签列表"""
        return self.editor.get_tags_to_add()

    def get_tags_to_remove(self) -> list[str]:
        """获取需要移除的标签列表 (即：现有标签中未被勾选的)"""
        return self.editor.get_tags_to_remove()
