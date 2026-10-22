# === 文件路径: src/ui/panels/file_list_panel.py ===
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,QGridLayout, QPushButton, QMenu, 
    QFileDialog, QMessageBox, QComboBox, QLabel, QLineEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from src.ui import themes
from src.ui.widgets.custom_table import CustomTable
from src.ui.dialogs.confirm_dialog import ConfirmDialog
from src.ui.dialogs.rename_dialog import RenameDialog
from src.ui.widgets.image_viewer import ImageViewer
from src.db.database import DatabaseManager
from src.db.dao import FileDAO, TagDAO, SettingsDAO
from src.core.file_service import FileService, STRATEGY_SKIP, STRATEGY_OVERWRITE, STRATEGY_RENAME
from src.core.models import FileRecord
from src.ui.qt_bridge import get_bridge
from src.core.thumbnail_engine import ThumbnailManager
from src.ui.widgets.image_delegate import ImageDelegate
from src.utils.file_utils import get_file_category

# 标签匹配方式：界面文案 ↔ DAO 参数值（顺序必须一致）
TAG_MODES_LABELS = ["包含", "为空", "不为空"]
TAG_MODES_KEYS = ["contains", "empty", "not_empty"]

class FileListPanel(QWidget):
    # 增加“状态”“标签”列
    COLUMNS = ["预览", "文件名", "状态", "类型", "标签", "大小(Byte)", "修改时间", "MD5", "完整路径"]
    COLUMN_KEYS = ["name", "name", "status_str", "file_category", "tags_str", "size",
                   "modified_time", "md5", "path"]

    def __init__(self, db_manager: DatabaseManager, file_service: FileService):
        super().__init__()
        self.db = db_manager
        self.file_dao = FileDAO(db_manager)
        self.tag_dao = TagDAO(db_manager)
        self.settings_dao = SettingsDAO(db_manager)
        self.file_service = file_service
        self.bridge = get_bridge()
        
        self.current_page = 1
        self.total_count = 0
        self.search_folder = ""
        self.search_name = ""
        self.search_md5 = ""
        self.search_type = ""
        self.search_tags = [] # 存储选中的标签ID或名称
        self._tag_query_mode = False  # 标签组合查询：无分页，数据已全量加载
        
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

        # 标签匹配方式：为空/不为空时不使用右侧标签文字
        self.combo_tag_op = QComboBox()
        self.combo_tag_op.addItems(TAG_MODES_LABELS)
        self.combo_tag_op.setFixedWidth(72)
        self.combo_tag_op.setToolTip("标签匹配方式：为空=没有任何标签；不为空=至少有一个标签")

        tag_layout = QHBoxLayout()
        tag_layout.setContentsMargins(0, 0, 0, 0)
        tag_layout.setSpacing(4)
        tag_layout.addWidget(self.combo_tag_op)
        tag_layout.addWidget(self.combo_tag_search, 1)

        grid_layout.addWidget(QLabel("路径:"), 0, 0)
        grid_layout.addWidget(self.input_folder, 0, 1)
        grid_layout.addWidget(QLabel("名称:"), 0, 2)
        grid_layout.addWidget(self.input_name, 0, 3)
        grid_layout.addWidget(QLabel("标签:"), 0, 4)
        grid_layout.addLayout(tag_layout, 0, 5)

        # --- 第二行：类型、MD5、搜索、清空 ---
        self.input_type = QLineEdit()
        self.input_type.setPlaceholderText("🏷️ 类型(如:jpg,mp4)...")
        self.input_type.setMinimumWidth(100)
        
        self.input_md5 = QLineEdit()
        self.input_md5.setPlaceholderText("#️⃣ MD5 精确匹配...")
        self.input_md5.setMinimumWidth(140)
        
        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.setFixedWidth(80)
        self.btn_search.setObjectName("primaryButton")
        
        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setFixedWidth(80)

        grid_layout.addWidget(QLabel("类型:"), 1, 0)
        grid_layout.addWidget(self.input_type, 1, 1)
        grid_layout.addWidget(QLabel("MD5:"), 1, 2)
        grid_layout.addWidget(self.input_md5, 1, 3)
        grid_layout.addWidget(self.btn_search, 1, 4)
        grid_layout.addWidget(self.btn_clear, 1, 5)

        # --- 第三行：宽度、高度筛选（操作符 + 数值） ---
        _DIM_OPS = ["不限", "=", ">", "<", "≥", "≤"]
        self.combo_width_op = QComboBox()
        self.combo_width_op.addItems(_DIM_OPS)
        self.combo_width_op.setFixedWidth(64)
        self.input_width = QLineEdit()
        self.input_width.setPlaceholderText("宽度 px...")

        width_layout = QHBoxLayout()
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.setSpacing(4)
        width_layout.addWidget(self.combo_width_op)
        width_layout.addWidget(self.input_width, 1)

        self.combo_height_op = QComboBox()
        self.combo_height_op.addItems(_DIM_OPS)
        self.combo_height_op.setFixedWidth(64)
        self.input_height = QLineEdit()
        self.input_height.setPlaceholderText("高度 px...")

        height_layout = QHBoxLayout()
        height_layout.setContentsMargins(0, 0, 0, 0)
        height_layout.setSpacing(4)
        height_layout.addWidget(self.combo_height_op)
        height_layout.addWidget(self.input_height, 1)

        grid_layout.addWidget(QLabel("宽度:"), 2, 0)
        grid_layout.addLayout(width_layout, 2, 1)
        grid_layout.addWidget(QLabel("高度:"), 2, 2)
        grid_layout.addLayout(height_layout, 2, 3)

        # 宽高比筛选：W:H 格式，默认 63:88；留空表示不筛选；可切换“等于/不等于”
        self.combo_aspect_op = QComboBox()
        self.combo_aspect_op.addItems(["=", "≠"])
        self.combo_aspect_op.setFixedWidth(48)
        self.combo_aspect_op.setToolTip("= 只保留该比例；≠ 排除该比例")
        self.input_aspect = QLineEdit("63:88")
        self.input_aspect.setPlaceholderText("如 16:9")
        self.input_aspect.setToolTip("宽高比筛选，格式 宽:高（如 63:88、16:9），1% 容差匹配等比缩放，留空不筛选")

        aspect_layout = QHBoxLayout()
        aspect_layout.setContentsMargins(0, 0, 0, 0)
        aspect_layout.setSpacing(4)
        aspect_layout.addWidget(self.combo_aspect_op)
        aspect_layout.addWidget(self.input_aspect, 1)

        grid_layout.addWidget(QLabel("宽高比:"), 2, 4)
        grid_layout.addLayout(aspect_layout, 2, 5)
        
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
        page_layout.addWidget(QLabel("每页:"))
        self.combo_page_size = QComboBox()
        self.combo_page_size.addItems(["10", "25", "50", "100"])
        self.combo_page_size.setFixedWidth(60)
        page_layout.addWidget(self.combo_page_size)
        
        page_layout.addSpacing(12) # 间隔
        
        page_layout.addWidget(QLabel("冲突:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["跳过 (安全)", "覆盖 (危险)", "自动重命名"])
        self.conflict_combo.setFixedWidth(96)
        self.conflict_combo.setToolTip("移动/复制文件时，遇到同名文件的处理方式")
        page_layout.addWidget(self.conflict_combo)
        
        # 弹簧：把右侧的分页控件推到最右边
        page_layout.addStretch() 
        
        # 【右侧】：分页导航
        self.btn_prev = QPushButton("上一页")
        self.btn_prev.setFixedWidth(64)
        self.lbl_page_info = QLabel("第 1 / 1 页")
        self.lbl_page_info.setProperty("role", "muted")
        self.btn_next = QPushButton("下一页")
        self.btn_next.setFixedWidth(64)
        
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
            self.combo_tag_search.addItem(tag.tag_name)
        self.combo_tag_search.setEditText(current_text)

    def _bind_events(self):
        self.btn_search.clicked.connect(lambda: self._load_data(1))
        self.btn_clear.clicked.connect(self._clear_search)
        
        for inp in [self.input_folder, self.input_name, self.input_type, self.input_md5]:
            inp.returnPressed.connect(lambda: self._load_data(1))
        self.combo_tag_search.lineEdit().returnPressed.connect(lambda: self._load_data(1))
        self.input_width.returnPressed.connect(lambda: self._load_data(1))
        self.input_height.returnPressed.connect(lambda: self._load_data(1))
        self.input_aspect.returnPressed.connect(lambda: self._load_data(1))
        self.combo_tag_op.currentIndexChanged.connect(self._on_tag_mode_changed)
        self._on_tag_mode_changed()
        
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)
        self.combo_page_size.currentTextChanged.connect(self._on_page_size_changed)
        self.bridge.data_changed.connect(lambda: [self._refresh_tag_combo(), self.refresh()])
        self.table.row_right_clicked.connect(self._show_context_menu)
        
        # 监听表格单元格双击，如果是第一列则放大图片
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        
        # 监听局部缩略图更新信号，防止 UI 卡死
        self.bridge.thumbnail_updated.connect(self._on_thumbnail_updated)
        
        # 【新增 2】监听表格选中变化，发射全局信号同步右侧详情
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_thumbnail_updated(self, file_path: str, thumb_path: str):
        """局部刷新：只更新当前页中匹配的那一行，不重新查询数据库"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                record = item.data(Qt.UserRole)
                if record is not None and record.path == file_path:
                    # 更新内存中的数据（FileRecord 展示字段）
                    record.thumbnail_path = thumb_path
                    item.setData(Qt.UserRole, record)
                    # 强制重绘表格视口，触发 ImageDelegate 重新绘制图片
                    self.table.viewport().update()
                    break

    def _on_selection_changed(self):
        """当表格选中项改变时，通知全局更新右侧详情面板"""
        selected_data = self.table.get_selected_rows_data()
        if selected_data:
            self.bridge.file_selected.emit(selected_data[0])
        else:
            self.bridge.file_selected.emit(None)

    def _on_cell_double_clicked(self, row, col):
        if col == 0: # 预览列
            item = self.table.item(row, 0)
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    path = data.path
                    ext = path.split('.')[-1].lower() if '.' in path else ""
                    image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico'}

                    if ext in image_exts and os.path.exists(path):
                        self.open_image_viewer(path)
                    elif data.thumbnail_path:
                        # 如果不是图片文件但有缩略图（如视频），则显示缩略图
                        viewer = ImageViewer(data.thumbnail_path, self)
                        viewer.exec()

    def open_image_viewer(self, path: str) -> None:
        """打开图片查看器（查询条件内全局连续切换），供文件列表和详情面板共用。

        一次性加载当前查询条件下的全部图片路径列表，viewer 的上一张/下一张
        在整个查询结果中连续切换；标题分母为真实图片总数，不再受分页大小限制。
        """
        ext = path.split('.')[-1].lower() if '.' in path else ""
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico'}
        if ext not in image_exts or not os.path.exists(path):
            return

        if getattr(self, '_tag_query_mode', False):
            # 标签组合查询：表格已全量加载结果
            images = self._current_page_images(image_exts)
        else:
            # 普通分页查询：SQL 一次性拉取全部图片路径（仅 path 列，万级数据可忽略）
            images = self.file_dao.get_image_paths(**self.current_filters())
            # 兜底：path 可能不在列表里（失联标记过时等），确保包含
            if path not in images:
                images.insert(0, path)

        viewer = ImageViewer(
            path, self, image_list=images,
            file_dao=self.file_dao, tag_dao=self.tag_dao,
            file_service=self.file_service)
        # 查看器内改完标签 → 关闭后刷新列表/详情中的标签列
        viewer.tags_changed.connect(self.refresh)
        # 查看器内重命名/移动/删除 → 刷新列表数据
        viewer.data_changed.connect(self.refresh)
        viewer.exec()

    def _current_page_images(self, image_exts: set[str]) -> list[str]:
        """当前表格中所有存在的图片路径（标签查询模式下 = 全部结果）。"""
        paths = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            rec = item.data(Qt.UserRole)
            if rec is None:
                continue
            ext = rec.name.split('.')[-1].lower() if '.' in rec.name else ""
            if ext in image_exts and os.path.exists(rec.path):
                paths.append(rec.path)
        return paths

    def refresh(self) -> None:
        """刷新当前列表（元数据提取完成等场景），保持当前页/查询模式。"""
        if self._tag_query_mode and getattr(self, '_last_tag_query', None) is not None:
            self.load_tag_query_results(self._last_tag_query)
        else:
            self._load_data(self.current_page)

    def _clear_search(self):
        self.input_folder.clear(); self.input_name.clear()
        self.input_type.clear(); self.input_md5.clear()
        self.combo_tag_search.setEditText("")
        self.combo_tag_op.setCurrentIndex(0)
        self.combo_width_op.setCurrentIndex(0)
        self.input_width.clear()
        self.combo_height_op.setCurrentIndex(0)
        self.input_height.clear()
        self.combo_aspect_op.setCurrentIndex(0)
        self.input_aspect.clear()
        self._load_data(1)

    def _on_tag_mode_changed(self) -> None:
        """为空/不为空时无需输入标签文字，禁用输入框避免误解。"""
        is_contains = self.combo_tag_op.currentIndex() == 0
        self.combo_tag_search.setEnabled(is_contains)

    def _tag_mode(self) -> str:
        idx = self.combo_tag_op.currentIndex()
        return TAG_MODES_KEYS[idx] if 0 <= idx < len(TAG_MODES_KEYS) else "contains"

    def _aspect_op(self) -> str:
        return "!=" if self.combo_aspect_op.currentText() == "≠" else "="

    @staticmethod
    def _parse_aspect_filter(text: str) -> tuple[int | None, int | None]:
        """解析 'W:H' 比例输入，返回 (aw, ah)；留空或非法返回 (None, None)。"""
        text = text.strip()
        if not text or ':' not in text:
            return None, None
        parts = text.split(':')
        if len(parts) != 2:
            return None, None
        try:
            aw, ah = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None, None
        if aw <= 0 or ah <= 0:
            return None, None
        return aw, ah

    @staticmethod
    def _parse_dim_filter(op_combo, val_input):
        """解析宽高筛选条件，返回 (op, val) 或 (None, None)。"""
        op_text = op_combo.currentText()
        val_text = val_input.text().strip()
        if op_text == "不限" or not val_text:
            return None, None
        try:
            val = int(val_text)
        except ValueError:
            return None, None
        op_map = {"=": "=", ">": ">", "<": "<", "≥": ">=", "≤": "<="}
        return op_map.get(op_text), val

    def _load_data(self, page: int = 1):
        self._tag_query_mode = False
        self.current_page = page
        self.search_folder = self.input_folder.text().strip()
        self.search_name = self.input_name.text().strip()
        self.search_md5 = self.input_md5.text().strip()
        self.search_type = self.input_type.text().strip()

        # 解析标签搜索 (支持逗号分隔的多标签)；为空/不为空模式下忽略输入文字
        tag_mode = self._tag_mode()
        tag_input = self.combo_tag_search.currentText().strip()
        search_tag_names = (
            [t.strip() for t in tag_input.split(',') if t.strip()]
            if tag_mode == "contains" and tag_input else None
        )

        # 解析宽高筛选
        width_op, width_val = self._parse_dim_filter(self.combo_width_op, self.input_width)
        height_op, height_val = self._parse_dim_filter(self.combo_height_op, self.input_height)
        aspect_w, aspect_h = self._parse_aspect_filter(self.input_aspect.text())

        # 【核心修复】将过滤条件直接传给 DAO，由 SQL 保证 total_count 的绝对准确
        data, self.total_count = self.file_dao.get_files_page(
            page, self.page_size,
            folder_path=self.search_folder,
            file_name=self.search_name,
            md5=self.search_md5,
            file_type=self.search_type,
            tag_names=search_tag_names,
            width_op=width_op, width_val=width_val,
            height_op=height_op, height_val=height_val,
            aspect_w=aspect_w, aspect_h=aspect_h,
            tag_mode=tag_mode, aspect_op=self._aspect_op(),
        )

        self._render_records(data)

        # 计算总页数 (现在 self.total_count 是数据库返回的真实全局总数)
        total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.lbl_page_info.setText(f"第 {page} / {total_pages} 页 (共 {self.total_count} 条)")
        self.btn_prev.setEnabled(page > 1)
        self.btn_next.setEnabled(page < total_pages)

    def _render_records(self, data: list[FileRecord]):
        """填充表格并补充展示字段（普通分页与标签组合查询共用）。"""
        # 仅为 UI 展示补充字段 (不影响分页逻辑)
        for record in data:
            record.file_category = get_file_category(record.path)
            record.tags_str = self.file_dao.get_file_tags_str(record.id)
            record.status_str = "已失联" if record.missing else "正常"
            record.meta = self.file_dao.get_file_meta(record.id)

        self.table.load_data(data, self.COLUMN_KEYS)
        self._style_missing_rows(data)

        # 异步缩略图：只让视频去后台生成，图片直接用原图渲染
        video_exts = {'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'}
        for record in data:
            ext = record.name.split('.')[-1].lower()
            if ext in video_exts and not record.thumbnail_path:
                self.thumb_manager.add_task(record.path, record.md5)

    def load_tag_query_results(self, query):
        """条件构造器的组合标签查询结果（无分页，一次性展示）。"""
        self._tag_query_mode = True
        self._last_tag_query = query
        data = self.file_dao.get_files_by_tag_query(query)
        self.total_count = len(data)
        self._render_records(data)
        self.lbl_page_info.setText(f"标签筛选：共 {len(data)} 条")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

    def current_filters(self) -> dict:
        """当前筛选条件（供主窗口归集 / CSV 导出 / 图片查看器复用，键与 get_files_page 对齐）。"""
        tag_mode = self._tag_mode()
        tag_input = self.combo_tag_search.currentText().strip()
        width_op, width_val = self._parse_dim_filter(self.combo_width_op, self.input_width)
        height_op, height_val = self._parse_dim_filter(self.combo_height_op, self.input_height)
        aspect_w, aspect_h = self._parse_aspect_filter(self.input_aspect.text())
        return {
            "folder_path": self.input_folder.text().strip(),
            "file_name": self.input_name.text().strip(),
            "md5": self.input_md5.text().strip(),
            "file_type": self.input_type.text().strip(),
            "tag_names": [t.strip() for t in tag_input.split(',') if t.strip()]
                          if tag_mode == "contains" else None,
            "tag_mode": tag_mode,
            "width_op": width_op, "width_val": width_val,
            "height_op": height_op, "height_val": height_val,
            "aspect_w": aspect_w, "aspect_h": aspect_h,
            "aspect_op": self._aspect_op(),
        }

    def _style_missing_rows(self, data: list[FileRecord]):
        """失联记录的“状态”列标黄并加悬停说明。"""
        brush = QBrush(QColor(themes.warning_color()))
        for row_idx, record in enumerate(data):
            if not record.missing:
                continue
            item = self.table.item(row_idx, 2)
            if item:
                item.setForeground(brush)
                item.setToolTip("原路径的文件已不存在：可右键仅删除数据库记录，或恢复文件后重新扫描")

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

    def _show_context_menu(self, row: int, data, global_pos):
        menu = QMenu(self)

        act_open_dir = menu.addAction("打开文件目录")
        menu.addSeparator()
        act_rename = menu.addAction("重命名 (批量)")
        act_move = menu.addAction("移动到...")
        act_copy = menu.addAction("复制到...")
        menu.addSeparator()

        # 复制子菜单
        copy_menu = menu.addMenu("复制信息")
        act_copy_path = copy_menu.addAction("复制路径")
        act_copy_dir = copy_menu.addAction("复制文件夹地址")
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

        if action == act_open_dir: self._open_file_dir(selected_data[0].path)
        elif action == act_delete_phys: self._on_delete(selected_data, physical=True)
        elif action == act_delete_db: self._on_delete(selected_data, physical=False)
        elif action == act_move: self._on_transfer(selected_data, is_move=True)
        elif action == act_copy: self._on_transfer(selected_data, is_move=False)
        elif action == act_rename: self._on_rename(selected_data)
        elif action == act_tag: self._on_manage_tags(selected_data)
        elif action == act_copy_path: self._copy_to_clipboard("\n".join([d.path for d in selected_data]))
        elif action == act_copy_dir:
            # 多选时去重后逐行复制各文件所在目录
            dirs = list(dict.fromkeys(os.path.dirname(d.path) for d in selected_data))
            self._copy_to_clipboard("\n".join(dirs))
        elif action == act_copy_name: self._copy_to_clipboard("\n".join([d.name for d in selected_data]))
        elif action == act_copy_md5: self._copy_to_clipboard("\n".join([d.md5 for d in selected_data]))

    def _open_file_dir(self, path: str):
        from src.utils.file_utils import open_in_explorer
        open_in_explorer(path)

    def _copy_to_clipboard(self, text: str):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

    def _on_delete(self, selected_data: list[FileRecord], physical: bool = True):
        paths = [d.path for d in selected_data]
        if physical:
            msg = f"确定要将选中的 {len(paths)} 个文件移入回收站吗？"
            if ConfirmDialog.show_confirm("确认删除", msg, self):
                self.file_service.delete_files(paths, use_trash=True)
        else:
            msg = f"确定要仅从数据库中删除这 {len(paths)} 条记录吗？\n物理文件将被保留。"
            if ConfirmDialog.show_confirm("确认逻辑删除", msg, self):
                for p in paths:
                    self.file_dao.delete_file_by_path(p)
                self.bridge.data_changed.emit()

    def _on_transfer(self, selected_data: list[FileRecord], is_move: bool):
        paths = [d.path for d in selected_data]
        title = "选择目标文件夹" if is_move else "选择复制目标文件夹"
        target_dir = QFileDialog.getExistingDirectory(self, title)
        if target_dir:
            strategy = self._get_conflict_strategy()
            if is_move: self.file_service.move_files(paths, target_dir, conflict_strategy=strategy)
            else: self.file_service.copy_files(paths, target_dir, conflict_strategy=strategy)

    def _on_rename(self, selected_data: list[FileRecord]):
        dialog = RenameDialog(selected_data, self)
        if dialog.exec():
            rename_map = dialog.get_rename_map()
            success_count = 0
            for old_path, new_name in rename_map.items():
                res = self.file_service.rename_file(old_path, new_name)
                if res.success_count > 0: success_count += 1
            QMessageBox.information(self, "重命名完成", f"成功重命名 {success_count} 个文件。")

    def _on_manage_tags(self, selected_data: list[FileRecord]):
        from src.utils.tag_helper import manage_tags_for_files
        manage_tags_for_files(self, selected_data, self.tag_dao, self.file_service)

    def closeEvent(self, event):
        if hasattr(self, 'thumb_manager') and self.thumb_manager.is_alive():
            self.thumb_manager.stop()
            self.thumb_manager.join(2)
        super().closeEvent(event)