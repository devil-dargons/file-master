from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel
)
from PySide6.QtCore import Qt
from src.db.dao import TagDAO

class TagManageDialog(QDialog):
    """
    标签管理弹窗：支持勾选现有标签 + 输入新标签
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
        self._load_existing_tags()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. 现有标签列表 (复选框模式)
        layout.addWidget(QLabel("1. 勾选已有标签 (支持多选):"))
        self.tag_list = QListWidget()
        # 禁用常规选中高亮，完全依赖复选框状态，避免视觉混淆
        self.tag_list.setSelectionMode(QListWidget.NoSelection) 
        layout.addWidget(self.tag_list, 1) # 占据主要空间
        
        # 2. 新增标签输入框
        layout.addWidget(QLabel("2. 添加新标签 (多个请用英文逗号分隔):"))
        self.new_tag_input = QLineEdit()
        self.new_tag_input.setPlaceholderText("例如: 工作, 重要, 2024")
        layout.addWidget(self.new_tag_input)
        
        # 3. 底部按钮
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

    def _load_existing_tags(self):
        """加载所有标签，并根据当前文件的绑定状态设置复选框"""
        all_tags = self.tag_dao.get_all_tags()
        # 获取该文件当前已绑定的标签
        file_tags = self.tag_dao.get_tags_by_file_id(self.file_id)
        file_tag_ids = {t['id'] for t in file_tags}
        
        for tag in all_tags:
            item = QListWidgetItem(tag['tag_name'])
            # 开启复选框功能
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            
            # 如果文件已有此标签，则默认勾选
            if tag['id'] in file_tag_ids:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            
            # 绑定 tag_id 以便后续识别
            item.setData(Qt.UserRole, tag['id'])
            self.tag_list.addItem(item)

    def get_tags_to_add(self) -> list[str]:
        """获取最终需要添加的标签列表"""
        # 1. 从输入框获取新标签
        new_tags_text = self.new_tag_input.text().strip()
        new_tags = [t.strip() for t in new_tags_text.split(',') if t.strip()]
        
        # 2. 从列表获取被勾选的标签
        checked_tags = []
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Checked:
                checked_tags.append(item.text())
                
        # 合并并去重
        return list(set(new_tags + checked_tags))

    def get_tags_to_remove(self) -> list[str]:
        """获取需要移除的标签列表 (即：现有标签中未被勾选的)"""
        removed_tags = []
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Unchecked:
                removed_tags.append(item.text())
        return removed_tags