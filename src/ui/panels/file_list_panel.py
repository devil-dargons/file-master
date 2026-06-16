# === 文件路径: src/ui/panels/file_list_panel.py ===
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,QGridLayout, QPushButton, QMenu, 
    QFileDialog, QInputDialog, QMessageBox, QComboBox, QLabel, QLineEdit,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from src.ui.widgets.custom_table import CustomTable
from src.ui.dialogs.confirm_dialog import ConfirmDialog
from src.ui.dialogs.rename_dialog import RenameDialog
from src.ui.dialogs.tag_manage_dialog import TagManageDialog
from src.ui.widgets.image_viewer import ImageViewer
from src.db.database_manager import DatabaseManager
from src.db.dao import FileDAO, TagDAO, SettingsDAO
from src.core.file_service import FileService, STRATEGY_SKIP, STRATEGY_OVERWRITE, STRATEGY_RENAME
from src.core.signals import AppSignals
from src.core.thumbnail_engine import ThumbnailManager
from src.ui.widgets.image_delegate import ImageDelegate
from src.utils.file_utils import get_file_category

class FileListPanel(QWidget):
    # 增加“标签”列
    COLUMNS = ["预览", "文件名", "类型", "标签", "大小(Byte)", "修改时间", "MD5", "完整路径"]
    COLUMN_KEYS = ["name", "name", "file_category", "tags_str", "size", "modified_time", "md5", "path"]

    def __init__(self, db_manager: DatabaseManager, file_service: FileService):
        super().__init__()
        self.db = db_manager
        self.file_dao = FileDAO(db_manager)
        self.tag_dao = TagDAO(db_manager)
        self.settings_dao = SettingsDAO(db_manager)
        self.file_service = file_service
        self.signals = AppSignals()
        
        self.current_page = 1
        self.total_count = 0
        self.search_folder = ""
        self.search_name = ""
        self.search_md5 = ""
        self.search_type = ""
        self.search_tags = [] # 存储选中的标签ID或名称
        
        saved_size = self.settings_dao.get_setting('page_size', '50')
        try: self.page_size = int(saved_size)
        except: self.page_size = 50
            
        self._init_ui()
        self._bind_events()
        
        self.thumb_manager = ThumbnailManager()
        self.thumb_manager.start()
        self._load_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # ==========================================
        # 1. 顶部：搜索条件区 (按照要求重新排序)
        # ==========================================
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(8, 8, 8, 8)
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)
        
        # --- 第一行：路径、名称、标签 ---
        self.input_folder = QLineEdit()
        self.input_folder.setPlaceholderText("📂 路径包含...")
        self.input_folder.setMinimumWidth(120)
        
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("🔍 文件名包含...")
        self.input_name.setMinimumWidth(120)
        
        self.combo_tag_search = QComboBox()
        self.combo_tag_search.setEditable(True)
        self.combo_tag_search.setPlaceholderText("🔖 标签筛选 (支持逗号分隔)...")
        self.combo_tag_search.setMinimumWidth(150)

        grid_layout.addWidget(QLabel("路径:"), 0, 0)
        grid_layout.addWidget(self.input_folder, 0, 1)
        grid_layout.addWidget(QLabel("名称:"), 0, 2)
        grid_layout.addWidget(self.input_name, 0, 3)
        grid_layout.addWidget(QLabel("标签:"), 0, 4)
        grid_layout.addWidget(self.combo_tag_search, 0, 5)

        # --- 第二行：类型、MD5、搜索、清空 ---
        self.input_type = QLineEdit()
        self.input_type.setPlaceholderText("🏷️ 类型(如:jpg,mp4)...")
        self.input_type.setMinimumWidth(100)
        
        self.input_md5 = QLineEdit()
        self.input_md5.setPlaceholderText("#️⃣ MD5 精确匹配...")
        self.input_md5.setMinimumWidth(140)
        
        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.setFixedWidth(80)
        self.btn_search.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; border-radius: 4px;")
        
        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setFixedWidth(80)

        grid_layout.addWidget(QLabel("类型:"), 1, 0)
        grid_layout.addWidget(self.input_type, 1, 1)
        grid_layout.addWidget(QLabel("MD5:"), 1, 2)
        grid_layout.addWidget(self.input_md5, 1, 3)
        grid_layout.addWidget(self.btn_search, 1, 4)
        grid_layout.addWidget(self.btn_clear, 1, 5)
        
        # 让输入框所在的列(1, 3, 5)自动拉伸，填满窗口宽度
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(3, 1)
        grid_layout.setColumnStretch(5, 1)

        main_layout.addLayout(grid_layout)
        
        # ==========================================
        # 2. 中间：核心数据表格
        # ==========================================
        self.table = CustomTable()
        self.table.set_columns(self.COLUMNS)
        self.table.setItemDelegateForColumn(0, ImageDelegate(self.table))
        self.table.setSelectionMode(CustomTable.ExtendedSelection)
        main_layout.addWidget(self.table, 1)
        
        # ==========================================
        # 3. 底部：分页控制与全局策略 (左右调换)
        # ==========================================
        page_layout = QHBoxLayout()
        
        # 【左侧】：列表控制与操作策略
        page_layout.addWidget(QLabel("每页显示:"))
        self.combo_page_size = QComboBox()
        self.combo_page_size.addItems(["10", "25", "50", "100"])
        self.combo_page_size.setFixedWidth(70)
        page_layout.addWidget(self.combo_page_size)
        
        page_layout.addSpacing(20) # 间隔
        
        page_layout.addWidget(QLabel("冲突策略:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["跳过 (安全)", "覆盖 (危险)", "自动重命名"])
        self.conflict_combo.setFixedWidth(110)
        self.conflict_combo.setToolTip("移动/复制文件时，遇到同名文件的处理方式")
        page_layout.addWidget(self.conflict_combo)
        
        # 弹簧：把右侧的分页控件推到最右边
        page_layout.addStretch() 
        
        # 【右侧】：分页导航
        self.btn_prev = QPushButton("上一页")
        self.btn_prev.setFixedWidth(80)
        self.lbl_page_info = QLabel("第 1 / 1 页")
        self.lbl_page_info.setStyleSheet("color: #666; padding: 0 10px;")
        self.btn_next = QPushButton("下一页")
        self.btn_next.setFixedWidth(80)
        
        page_layout.addWidget(self.btn_prev)
        page_layout.addWidget(self.lbl_page_info)
        page_layout.addWidget(self.btn_next)

        main_layout.addLayout(page_layout)

    def _refresh_tag_combo(self):
        """刷新标签下拉框内容"""
        current_text = self.combo_tag_search.currentText()
        self.combo_tag_search.clear()
        tags = self.tag_dao.get_all_tags()
        for tag in tags:
            self.combo_tag_search.addItem(tag['tag_name'])
        self.combo_tag_search.setEditText(current_text)

    def _bind_events(self):
        self.btn_search.clicked.connect(lambda: self._load_data(1))
        self.btn_clear.clicked.connect(self._clear_search)
        
        for inp in [self.input_folder, self.input_name, self.input_type, self.input_md5]:
            inp.returnPressed.connect(lambda: self._load_data(1))
        self.combo_tag_search.lineEdit().returnPressed.connect(lambda: self._load_data(1))
        
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)
        self.combo_page_size.currentTextChanged.connect(self._on_page_size_changed)
        self.signals.data_changed.connect(lambda: [self._refresh_tag_combo(), self._load_data(self.current_page)])
        self.table.row_right_clicked.connect(self._show_context_menu)
        
        # 监听表格单元格双击，如果是第一列则放大图片
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        
        # 【新增 1】监听局部缩略图更新信号，防止 UI 卡死
        self.signals.thumbnail_updated.connect(self._on_thumbnail_updated)
        
        # 【新增 2】监听表格选中变化，发射全局信号同步右侧详情
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_thumbnail_updated(self, file_path: str, thumb_path: str):
        """局部刷新：只更新当前页中匹配的那一行，不重新查询数据库"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                data = item.data(Qt.UserRole)
                if data and data.get('path') == file_path:
                    # 更新内存中的数据
                    data['thumbnail_path'] = thumb_path
                    item.setData(Qt.UserRole, data)
                    # 强制重绘表格视口，触发 ImageDelegate 重新绘制图片
                    self.table.viewport().update()
                    break # 找到并更新后即可退出循环

    def _on_selection_changed(self):
        """当表格选中项改变时，通知全局更新右侧详情面板"""
        selected_data = self.table.get_selected_rows_data()
        if selected_data:
            self.signals.file_selected.emit(selected_data[0])
        else:
            self.signals.file_selected.emit({})

    def _on_cell_double_clicked(self, row, col):
        if col == 0: # 预览列
            item = self.table.item(row, 0)
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    path = data['path']
                    ext = path.split('.')[-1].lower() if '.' in path else ""
                    image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico'}
                    
                    if ext in image_exts and os.path.exists(path):
                        # 核心修改：直接使用原图路径创建查看器
                        viewer = ImageViewer(path, self)
                        viewer.exec()
                    elif data.get('thumbnail_path'):
                        # 如果不是图片文件但有缩略图（如视频），则显示缩略图
                        viewer = ImageViewer(data['thumbnail_path'], self)
                        viewer.exec()

    def _clear_search(self):
        self.input_folder.clear(); self.input_name.clear()
        self.input_type.clear(); self.input_md5.clear()
        self.combo_tag_search.setEditText("")
        self._load_data(1)

    def _load_data(self, page: int = 1):
        self.current_page = page
        self.search_folder = self.input_folder.text().strip()
        self.search_name = self.input_name.text().strip()
        self.search_md5 = self.input_md5.text().strip()
        self.search_type = self.input_type.text().strip()
        
        # 解析标签搜索 (支持逗号分隔的多标签)
        tag_input = self.combo_tag_search.currentText().strip()
        search_tag_names = [t.strip() for t in tag_input.split(',') if t.strip()] if tag_input else None

        # 【核心修复】将过滤条件直接传给 DAO，由 SQL 保证 total_count 的绝对准确
        data, self.total_count = self.file_dao.get_files_page(
            page, self.page_size, 
            folder_path=self.search_folder, 
            file_name=self.search_name, 
            md5=self.search_md5,
            file_type=self.search_type,
            tag_names=search_tag_names
        )
        
        # 仅为 UI 展示补充字段 (不影响分页逻辑)
        for item in data:
            item['file_category'] = get_file_category(item['path'])
            item['tags_str'] = self.file_dao.get_file_tags_str(item['id'])

        self.table.load_data(data, self.COLUMN_KEYS)
        
        # 计算总页数 (现在 self.total_count 是数据库返回的真实全局总数)
        total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.lbl_page_info.setText(f"第 {page} / {total_pages} 页 (共 {self.total_count} 条)")
        self.btn_prev.setEnabled(page > 1)
        self.btn_next.setEnabled(page < total_pages)
        
        # 异步缩略图：只让视频去后台生成，图片直接用原图渲染
        video_exts = {'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'}
        for row_data in data:
            thumb_path = row_data.get('thumbnail_path')
            ext = row_data['name'].split('.')[-1].lower()
            if ext in video_exts and not thumb_path:
                self.thumb_manager.add_task(row_data['path'], row_data['md5'])

    def _prev_page(self):
        if self.current_page > 1: self._load_data(self.current_page - 1)
    def _next_page(self):
        total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        if self.current_page < total_pages: self._load_data(self.current_page + 1)
    def _on_page_size_changed(self, text: str):
        try:
            new_size = int(text); self.page_size = new_size
            self.settings_dao.set_setting('page_size', str(new_size))
            self._load_data(1)
        except ValueError: pass

    def _get_conflict_strategy(self) -> str:
        idx = self.conflict_combo.currentIndex()
        if idx == 0: return STRATEGY_SKIP
        if idx == 1: return STRATEGY_OVERWRITE
        return STRATEGY_RENAME

    def _show_context_menu(self, row: int, data: dict, global_pos):
        menu = QMenu(self)
        
        act_rename = menu.addAction("重命名 (批量)")
        act_move = menu.addAction("移动到...")
        act_copy = menu.addAction("复制到...")
        menu.addSeparator()
        
        # 复制子菜单
        copy_menu = menu.addMenu("复制信息")
        act_copy_path = copy_menu.addAction("复制路径")
        act_copy_name = copy_menu.addAction("复制文件名")
        act_copy_md5 = copy_menu.addAction("复制 MD5")
        
        menu.addSeparator()
        act_tag = menu.addAction("管理标签...")
        menu.addSeparator()
        act_delete_phys = menu.addAction("删除 (移入回收站)")
        act_delete_db = menu.addAction("仅删除数据库记录 (保留文件)")

        selected_data = self.table.get_selected_rows_data()
        if not selected_data: return

        action = menu.exec(global_pos)
        
        if action == act_delete_phys: self._on_delete(selected_data, physical=True)
        elif action == act_delete_db: self._on_delete(selected_data, physical=False)
        elif action == act_move: self._on_transfer(selected_data, is_move=True)
        elif action == act_copy: self._on_transfer(selected_data, is_move=False)
        elif action == act_rename: self._on_rename(selected_data)
        elif action == act_tag: self._on_manage_tags(selected_data)
        elif action == act_copy_path: self._copy_to_clipboard("\n".join([d['path'] for d in selected_data]))
        elif action == act_copy_name: self._copy_to_clipboard("\n".join([d['name'] for d in selected_data]))
        elif action == act_copy_md5: self._copy_to_clipboard("\n".join([d['md5'] for d in selected_data]))

    def _copy_to_clipboard(self, text: str):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

    def _on_delete(self, selected_data: list[dict], physical: bool = True):
        paths = [d['path'] for d in selected_data]
        if physical:
            msg = f"确定要将选中的 {len(paths)} 个文件移入回收站吗？"
            if ConfirmDialog.show_confirm("确认删除", msg, self):
                self.file_service.delete_files(paths, use_trash=True)
        else:
            msg = f"确定要仅从数据库中删除这 {len(paths)} 条记录吗？\n物理文件将被保留。"
            if ConfirmDialog.show_confirm("确认逻辑删除", msg, self):
                for p in paths:
                    self.file_dao.delete_file_by_path(p)
                self.signals.data_changed.emit()

    def _on_transfer(self, selected_data: list[dict], is_move: bool):
        paths = [d['path'] for d in selected_data]
        title = "选择目标文件夹" if is_move else "选择复制目标文件夹"
        target_dir = QFileDialog.getExistingDirectory(self, title)
        if target_dir:
            strategy = self._get_conflict_strategy()
            if is_move: self.file_service.move_files(paths, target_dir, conflict_strategy=strategy)
            else: self.file_service.copy_files(paths, target_dir, conflict_strategy=strategy)

    def _on_rename(self, selected_data: list[dict]):
        dialog = RenameDialog(selected_data, self)
        if dialog.exec():
            rename_map = dialog.get_rename_map()
            success_count = 0
            for old_path, new_name in rename_map.items():
                res = self.file_service.rename_file(old_path, new_name)
                if res['data']['success_count'] > 0: success_count += 1
            QMessageBox.information(self, "重命名完成", f"成功重命名 {success_count} 个文件。")

    def _on_manage_tags(self, selected_data: list[dict]):
        from src.utils.tag_helper import manage_tags_for_files
        manage_tags_for_files(self, selected_data, self.tag_dao, self.file_service)

    def closeEvent(self, event):
        if hasattr(self, 'thumb_manager') and self.thumb_manager.isRunning():
            self.thumb_manager.stop()
            self.thumb_manager.wait(2000)
        super().closeEvent(event)