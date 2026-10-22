# === 文件路径: src/ui/panels/duplicate_panel.py ===
from __future__ import annotations
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, 
    QTreeWidgetItem, QHeaderView, QMenu, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.db.database import DatabaseManager
from src.db.dao import FileDAO
from src.core.file_service import FileService, STRATEGY_SKIP
from src.core.models import FileRecord
from src.ui.qt_bridge import get_bridge
from src.ui.dialogs.confirm_dialog import ConfirmDialog
from src.ui.dialogs.rename_dialog import RenameDialog

class DuplicatePanel(QWidget):
    TREE_COLUMNS = ["文件信息 / MD5摘要", "大小", "修改时间", "完整路径"]

    def __init__(self, db_manager: DatabaseManager, file_service: FileService):
        super().__init__()
        self.db = db_manager
        self.file_dao = FileDAO(db_manager)
        self.file_service = file_service
        self.bridge = get_bridge()
        
        self._init_ui()
        self._bind_events()
        self._load_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        
        self.btn_refresh = QPushButton("刷新去重数据")
        toolbar.addWidget(self.btn_refresh)
        
        self.btn_auto_clean = QPushButton("⚡ 一键智能清理 (保留每组首个)")
        self.btn_auto_clean.setObjectName("dangerButton")
        toolbar.addWidget(self.btn_auto_clean)
        
        self.btn_move_all = QPushButton("批量移动本组其余文件...")
        toolbar.addWidget(self.btn_move_all)
        toolbar.addStretch()
        
        self.lbl_summary = QPushButton("共 0 组重复文件")
        self.lbl_summary.setEnabled(False)
        toolbar.addWidget(self.lbl_summary)
        main_layout.addLayout(toolbar)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.TREE_COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        main_layout.addWidget(self.tree, 1)

    def _bind_events(self):
        self.btn_refresh.clicked.connect(self._load_data)
        self.btn_auto_clean.clicked.connect(self._on_auto_clean)
        self.btn_move_all.clicked.connect(self._on_move_all_groups)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.bridge.data_changed.connect(self._load_data)
        
        # 【新增】绑定树形控件的选中事件，用于同步右侧详情面板
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        """当去重列表选中项改变时，通知全局更新右侧详情面板"""
        selected_items = self.tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            data = item.data(0, Qt.UserRole)
            # 确保选中的是具体的文件节点，而不是 MD5 分组节点
            if data and data.get('type') == 'file':
                file_data = data.get('data')
                if file_data:
                    self.bridge.file_selected.emit(file_data)
                    return

        # 如果选中的是分组节点，或者取消了选中，则清空右侧详情
        self.bridge.file_selected.emit(None)

    def _load_data(self):
        self.tree.clear()
        groups = self.file_dao.get_duplicate_groups()
        
        total_groups = len(groups)
        total_files = sum(g.count for g in groups)
        self.lbl_summary.setText(f"共 {total_groups} 组重复，涉及 {total_files} 个文件")

        for group in groups:
            md5 = group.md5
            files = group.files
            
            group_text = f"MD5: {md5[:16]}... (共 {len(files)} 个重复文件)"
            group_item = QTreeWidgetItem(self.tree, [group_text, "", "", ""])
            group_item.setData(0, Qt.UserRole, {"type": "group", "md5": md5, "files": files})
            group_item.setExpanded(False)
            group_item.setForeground(0, QColor("#1976D2"))
            group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
            
            for file_data in files:
                size_str = self._format_size(file_data.size)
                time_str = self._format_time(file_data.modified_time)

                item = QTreeWidgetItem(group_item, [
                    file_data.name, size_str, time_str, file_data.path
                ])
                item.setData(0, Qt.UserRole, {"type": "file", "data": file_data})
                item.setToolTip(3, file_data.path)

    def _format_size(self, size_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def _format_time(self, timestamp: float) -> str:
        if not timestamp: return ""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item: return
        data = item.data(0, Qt.UserRole)
        if not data: return

        menu = QMenu(self)
        if data['type'] == 'group':
            act_clean = menu.addAction("⚡ 智能清理此组 (保留第一个)")
            act_move_rest = menu.addAction("移动此组其余文件到...")
            action = menu.exec(self.tree.mapToGlobal(pos))
            if action == act_clean: self._clean_group(item, keep_index=0)
            elif action == act_move_rest: self._move_rest_of_group(item)
        elif data['type'] == 'file':
            file_data = data['data']
            act_keep = menu.addAction("✅ 保留此项，清理同组其他")
            act_rename = menu.addAction("重命名...")
            act_move = menu.addAction("移动此项到...")
            act_delete = menu.addAction("删除此项")
            
            action = menu.exec(self.tree.mapToGlobal(pos))
            if action == act_keep: self._keep_this_file(item)
            elif action == act_rename: self._rename_single_file(file_data)
            elif action == act_move: self._transfer_single_file(file_data, is_move=True)
            elif action == act_delete: self._delete_single_file(file_data)

    def _clean_group(self, group_item: QTreeWidgetItem, keep_index: int = 0):
        files = [group_item.child(i).data(0, Qt.UserRole)['data'] for i in range(group_item.childCount())]
        if len(files) <= 1: return
        keep_file = files[keep_index]
        to_delete_paths = [f.path for i, f in enumerate(files) if i != keep_index]
        msg = f"确定要清理此重复组吗？\n\n【保留】: {keep_file.name}\n【删除】: {len(to_delete_paths)} 个其他副本\n(删除的文件将移入回收站)"
        if ConfirmDialog.show_confirm("确认智能清理", msg, self):
            self.file_service.delete_files(to_delete_paths, use_trash=True)

    def _keep_this_file(self, file_item: QTreeWidgetItem):
        group_item = file_item.parent()
        if not group_item: return
        self._clean_group(group_item, keep_index=group_item.indexOfChild(file_item))

    def _on_auto_clean(self):
        top_count = self.tree.topLevelItemCount()
        if top_count == 0:
            QMessageBox.information(self, "提示", "当前没有检测到重复文件。")
            return
        msg = f"⚠️ 极度危险操作警告！\n\n即将对全部 {top_count} 组重复文件执行智能清理。\n规则：保留每组列表中的【第 1 个】文件，删除其余所有副本。\n\n确定要继续吗？"
        if ConfirmDialog.show_confirm("一键智能清理确认", msg, self):
            total_deleted = 0
            for i in range(top_count):
                group_item = self.tree.topLevelItem(i)
                files = [group_item.child(j).data(0, Qt.UserRole)['data'] for j in range(group_item.childCount())]
                if len(files) > 1:
                    to_delete = [f.path for k, f in enumerate(files) if k != 0]
                    self.file_service.delete_files(to_delete, use_trash=True)
                    total_deleted += len(to_delete)
            QMessageBox.information(self, "清理完成", f"智能清理完成！共删除了 {total_deleted} 个重复副本。")

    def _move_rest_of_group(self, group_item: QTreeWidgetItem):
        target_dir = QFileDialog.getExistingDirectory(self, "选择移动目标文件夹")
        if not target_dir: return
        to_move_paths = [group_item.child(i).data(0, Qt.UserRole)['data'].path for i in range(1, group_item.childCount())]
        if to_move_paths:
            self.file_service.move_files(to_move_paths, target_dir, conflict_strategy=STRATEGY_SKIP)

    def _on_move_all_groups(self):
        target_dir = QFileDialog.getExistingDirectory(self, "选择移动目标文件夹")
        if not target_dir: return
        all_paths = []
        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            for j in range(1, group_item.childCount()):
                all_paths.append(group_item.child(j).data(0, Qt.UserRole)['data'].path)
        if all_paths:
            self.file_service.move_files(all_paths, target_dir, conflict_strategy=STRATEGY_SKIP)

    def _rename_single_file(self, file_data: FileRecord):
        dialog = RenameDialog([file_data], self)
        if dialog.exec():
            for old_path, new_name in dialog.get_rename_map().items():
                self.file_service.rename_file(old_path, new_name)

    def _transfer_single_file(self, file_data: FileRecord, is_move: bool):
        target_dir = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if target_dir:
            if is_move:
                self.file_service.move_files([file_data.path], target_dir, STRATEGY_SKIP)
            else:
                self.file_service.copy_files([file_data.path], target_dir, STRATEGY_SKIP)

    def _delete_single_file(self, file_data: FileRecord):
        if ConfirmDialog.show_confirm("确认删除", f"确定要将 {file_data.name} 移入回收站吗？", self):
            self.file_service.delete_files([file_data.path], use_trash=True)