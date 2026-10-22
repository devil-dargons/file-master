from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, 
    QListWidgetItem, QMenu, QMessageBox, QInputDialog, QSplitter, QLabel
)
from PySide6.QtCore import Qt

from src.ui.widgets.custom_table import CustomTable
from src.ui.dialogs.confirm_dialog import ConfirmDialog
from src.ui.dialogs.rename_dialog import RenameDialog
from src.db.database import DatabaseManager
from src.db.dao import FileDAO, TagDAO
from src.core.file_service import FileService, STRATEGY_SKIP
from src.core.models import FileRecord
from src.ui.qt_bridge import get_bridge
from src.utils.tag_helper import manage_tags_for_files

class TagPanel(QWidget):
    """
    标签管理与多标签组合搜索面板
    """
    
    COLUMNS = ["文件名", "大小(Byte)", "修改时间", "MD5", "完整路径"]
    COLUMN_KEYS = ["name", "size", "modified_time", "md5", "path"]

    def __init__(self, db_manager: DatabaseManager, file_service: FileService):
        super().__init__()
        self.db = db_manager
        self.file_dao = FileDAO(db_manager)
        self.tag_dao = TagDAO(db_manager)
        self.file_service = file_service
        self.bridge = get_bridge()
        
        self._init_ui()
        self._bind_events()
        self._load_tags()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # 1. 顶部提示与工具栏
        toolbar = QHBoxLayout()
        self.lbl_tip = QLabel("💡 提示：在左侧列表中按住 Ctrl 或 Shift 点击，可进行多标签组合搜索。")
        self.lbl_tip.setProperty("role", "muted")
        toolbar.addWidget(self.lbl_tip)
        toolbar.addStretch()
        
        self.btn_refresh = QPushButton("刷新")
        toolbar.addWidget(self.btn_refresh)
        main_layout.addLayout(toolbar)
        
        # 2. 核心左右分栏布局
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：标签列表与管理
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QListWidget.ExtendedSelection) # 支持多选
        self.tag_list.setAlternatingRowColors(True)
        left_layout.addWidget(self.tag_list, 1)
        
        tag_btn_layout = QHBoxLayout()
        self.btn_add_tag = QPushButton("+ 新标签")
        self.btn_del_tag = QPushButton("- 删标签")
        self.btn_clear_sel = QPushButton("清空选择")
        tag_btn_layout.addWidget(self.btn_add_tag)
        tag_btn_layout.addWidget(self.btn_del_tag)
        tag_btn_layout.addWidget(self.btn_clear_sel)
        left_layout.addLayout(tag_btn_layout)
        
        splitter.addWidget(left_widget)
        
        # 右侧：搜索结果表格
        self.table = CustomTable()
        self.table.set_columns(self.COLUMNS)
        splitter.addWidget(self.table)
        
        # 设置初始分割比例 (左3 : 右7)
        splitter.setSizes([200, 500])
        main_layout.addWidget(splitter, 1)

    def _bind_events(self):
        self.btn_refresh.clicked.connect(self._load_tags)
        self.btn_add_tag.clicked.connect(self._on_add_tag)
        self.btn_del_tag.clicked.connect(self._on_delete_tag)
        self.btn_clear_sel.clicked.connect(self.tag_list.clearSelection)
        
        # 标签选择改变时，触发组合搜索
        self.tag_list.itemSelectionChanged.connect(self._on_search_by_tags)
        
        # 表格右键菜单
        self.table.row_right_clicked.connect(self._show_context_menu)
        
        # 监听全局数据变化（如文件被删除、重命名），刷新当前结果
        self.bridge.data_changed.connect(self._on_search_by_tags)

    def _load_tags(self):
        """加载所有标签到左侧列表"""
        self.tag_list.clear()
        tags = self.tag_dao.get_all_tags()
        for tag in tags:
            item = QListWidgetItem(tag.tag_name)
            item.setData(Qt.UserRole, tag.id) # 绑定 tag_id
            self.tag_list.addItem(item)
            
        # 加载完标签后，尝试刷新一下右侧表格（如果当前有选中的标签）
        self._on_search_by_tags()

    def _on_search_by_tags(self):
        """根据当前选中的标签组合，查询并展示文件"""
        selected_items = self.tag_list.selectedItems()
        tag_names = [item.text() for item in selected_items]
        
        if not tag_names:
            self.table.setRowCount(0)
            return
            
        # 调用 DAO 层的多标签交集查询
        files = self.file_dao.get_files_by_tags(tag_names)
        self.table.load_data(files, self.COLUMN_KEYS)

    def _on_add_tag(self):
        """新建标签"""
        text, ok = QInputDialog.getText(self, "新建标签", "请输入新标签名称:")
        if ok and text.strip():
            tag_name = text.strip()
            tag_id = self.tag_dao.add_tag(tag_name)
            if tag_id != -1:
                # 刷新列表
                self._load_tags()
            else:
                QMessageBox.warning(self, "错误", "标签已存在或添加失败。")

    def _on_delete_tag(self):
        """删除选中的标签（仅删除标签本身，不删除物理文件）"""
        selected_items = self.tag_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先在左侧选择要删除的标签。")
            return
            
        tag_names = [item.text() for item in selected_items]
        msg = f"确定要删除以下标签吗？\n\n{', '.join(tag_names)}\n\n(注意：这只会删除标签，不会删除关联的物理文件)"
        
        if ConfirmDialog.show_confirm("确认删除标签", msg, self):
            for item in selected_items:
                tag_id = item.data(Qt.UserRole)
                self.tag_dao.delete_tag(tag_id)
            self._load_tags()

    # ==========================================
    # 表格右键菜单逻辑 (与 FileListPanel 类似)
    # ==========================================
    def _show_context_menu(self, row: int, data, global_pos):
        menu = QMenu(self)
        
        act_rename = menu.addAction("重命名 (批量)")
        act_move = menu.addAction("移动到...")
        act_copy = menu.addAction("复制到...")
        menu.addSeparator()
        act_tag = menu.addAction("管理标签...")
        menu.addSeparator()
        act_delete = menu.addAction("删除 (移入回收站)")

        selected_data = self.table.get_selected_rows_data()
        if not selected_data:
            return

        # 使用传入的 global_pos 准确显示菜单
        action = menu.exec(global_pos)
        
        if action == act_delete:
            self._on_delete(selected_data)
        elif action == act_move:
            self._on_transfer(selected_data, is_move=True)
        elif action == act_copy:
            self._on_transfer(selected_data, is_move=False)
        elif action == act_rename:
            self._on_rename(selected_data)
        elif action == act_tag:
            self._on_manage_tags(selected_data)

    def _on_delete(self, selected_data: list[FileRecord]):
        paths = [d.path for d in selected_data]
        msg = f"确定要将选中的 {len(paths)} 个文件移入回收站吗？"
        if ConfirmDialog.show_confirm("确认删除", msg, self):
            self.file_service.delete_files(paths, use_trash=True)

    def _on_transfer(self, selected_data: list[FileRecord], is_move: bool):
        from PySide6.QtWidgets import QFileDialog
        paths = [d.path for d in selected_data]
        title = "选择目标文件夹" if is_move else "选择复制目标文件夹"
        target_dir = QFileDialog.getExistingDirectory(self, title)
        if target_dir:
            if is_move:
                self.file_service.move_files(paths, target_dir, conflict_strategy=STRATEGY_SKIP)
            else:
                self.file_service.copy_files(paths, target_dir, conflict_strategy=STRATEGY_SKIP)

    def _on_rename(self, selected_data: list[FileRecord]):
        dialog = RenameDialog(selected_data, self)
        if dialog.exec():
            rename_map = dialog.get_rename_map()
            success_count = 0
            for old_path, new_name in rename_map.items():
                res = self.file_service.rename_file(old_path, new_name)
                if res.success_count > 0:
                    success_count += 1
            QMessageBox.information(self, "重命名完成", f"成功重命名 {success_count} 个文件。")

    def _on_manage_tags(self, selected_data: list[FileRecord]):
        # 直接调用公共辅助函数，传入当前上下文 (self) 和所需依赖
        manage_tags_for_files(self, selected_data, self.tag_dao, self.file_service)