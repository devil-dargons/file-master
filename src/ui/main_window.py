# === 文件路径: src/ui/main_window.py ===
from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QListWidgetItem, QStackedWidget, QPushButton,
    QFileDialog, QProgressBar, QLabel, QCheckBox, QMessageBox,
    QStatusBar, QSplitter, QComboBox
)
from PySide6.QtCore import Qt, QSize
import re

from src.db.database_manager import DatabaseManager
from src.db.dao import FileDAO, TagDAO
from src.core.file_service import FileService
from src.core.scanner import FileScanner
from src.core.signals import AppSignals
from src.config import FILE_TYPE_PRESETS

from src.ui.panels.file_list_panel import FileListPanel
from src.ui.panels.duplicate_panel import DuplicatePanel
from src.ui.panels.tag_panel import TagPanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileMaster - 智能文件管家 v1.0")
        self.resize(1200, 650)
        self.setMinimumSize(800, 550) 
        
        self.db_manager = DatabaseManager()
        self.file_dao = FileDAO(self.db_manager)
        self.tag_dao = TagDAO(self.db_manager)
        self.file_service = FileService(self.file_dao, self.tag_dao)
        self.signals = AppSignals()
        
        self.scanner = None
        self.target_paths = []
        
        self._init_ui()
        self._bind_signals()
        
    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # ==========================================
        # 顶部：扫描控制台
        # ==========================================
        scan_toolbar = QHBoxLayout()
        
        self.btn_select_path = QPushButton("📁 选择扫描路径")
        self.btn_select_path.clicked.connect(self._on_select_path)
        scan_toolbar.addWidget(self.btn_select_path)
        
        self.lbl_current_path = QLabel("未选择路径")
        self.lbl_current_path.setStyleSheet("color: #666;")
        scan_toolbar.addWidget(self.lbl_current_path, 1)
        
        # 新增：扫描类型选择
        scan_toolbar.addWidget(QLabel("扫描类型:"))
        self.combo_scan_type = QComboBox()
        self.combo_scan_type.setEditable(True)
        self.combo_scan_type.addItems(FILE_TYPE_PRESETS)
        self.combo_scan_type.setFixedWidth(250)
        scan_toolbar.addWidget(self.combo_scan_type)
        
        self.chk_incremental = QCheckBox("增量扫描")
        self.chk_incremental.setChecked(True)
        scan_toolbar.addWidget(self.chk_incremental)
        
        self.btn_start_scan = QPushButton("▶ 开始扫描")
        self.btn_start_scan.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 15px; font-weight: bold;")
        self.btn_start_scan.clicked.connect(self._on_start_scan)
        scan_toolbar.addWidget(self.btn_start_scan)
        
        self.btn_stop_scan = QPushButton("⏹ 停止")
        self.btn_stop_scan.setEnabled(False)
        self.btn_stop_scan.clicked.connect(self._on_stop_scan)
        scan_toolbar.addWidget(self.btn_stop_scan)
        
        main_layout.addLayout(scan_toolbar)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("就绪")
        main_layout.addWidget(self.progress_bar)
        
        # ==========================================
        # 中部：左侧导航 + 中间面板 + 右侧详情
        # ==========================================
        content_splitter = QSplitter(Qt.Horizontal)
        
        # 1. 左侧导航栏
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160) # 稍微调窄
        self.nav_list.setIconSize(QSize(24, 24))
        self.nav_list.setStyleSheet("font-size: 14px; padding: 5px;")
        
        nav_items = [
            ("📂 全局文件列表", 0),
            ("🔄 重复文件清理", 1),
            ("🏷️ 标签与搜索", 2)
        ]
        for text, index in nav_items:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, index)
            self.nav_list.addItem(item)
            
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        content_splitter.addWidget(self.nav_list)
        
        # 2. 中间功能面板堆叠区
        self.stack = QStackedWidget()
        
        # 实例化各个功能面板
        self.panel_file_list = FileListPanel(self.db_manager, self.file_service)
        self.panel_duplicate = DuplicatePanel(self.db_manager, self.file_service)
        self.panel_tag = TagPanel(self.db_manager, self.file_service)
        
        self.stack.addWidget(self.panel_file_list)
        self.stack.addWidget(self.panel_duplicate)
        self.stack.addWidget(self.panel_tag)
        
        content_splitter.addWidget(self.stack)
        
        # 3. 【新增】右侧详情面板
        from src.ui.panels.detail_panel import DetailPanel
        self.panel_detail = DetailPanel()
        content_splitter.addWidget(self.panel_detail)
        
        # 【核心修改】调整初始比例，总和约 1050，防止窗口过宽超出屏幕无法缩小
        content_splitter.setSizes([140, 500, 260])
        main_layout.addWidget(content_splitter, 1)
        
        # ==========================================
        # 底部：全局状态栏
        # ==========================================
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("欢迎使用 FileMaster。请选择路径并开始扫描。")

        # ==========================================
        # 【核心修改】绑定全局联动信号
        # ==========================================
        # 移除原来局部的 table.itemSelectionChanged 绑定。
        # 改为监听全局信号：任何面板选中文件，都统一更新右侧详情面板
        self.signals.file_selected.connect(self.panel_detail.update_detail)
    
    # 注意：原有的 _on_selection_changed 方法已删除，因为现在由各个 Panel 自己发射全局信号。

    def _bind_signals(self):
        self.signals.scan_progress.connect(self._on_scan_progress)
        self.signals.scan_finished.connect(self._on_scan_finished)
        self.signals.file_operation_result.connect(self._on_operation_result)

    def _on_select_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择要扫描的文件夹")
        if path:
            self.target_paths = [path]
            self.lbl_current_path.setText(path)
            self.lbl_current_path.setStyleSheet("color: #000; font-weight: bold;")

    def _on_start_scan(self):
        if not self.target_paths:
            QMessageBox.warning(self, "提示", "请先选择要扫描的文件夹！")
            return
            
        # 解析扫描类型
        type_str = self.combo_scan_type.currentText().strip()
        include_exts = None
        if type_str and type_str != "全部":
            # 简单正则提取括号内的内容或按符号分割
            match = re.search(r'\((.*?)\)', type_str)
            if match:
                raw_exts = match.group(1).split(';')
            else:
                raw_exts = re.split(r'[,\s;]+', type_str)
            include_exts = {ext.strip().lstrip('*').lower() for ext in raw_exts if ext.strip()}
            
        is_incremental = self.chk_incremental.isChecked()
        
        self.btn_start_scan.setEnabled(False)
        self.btn_stop_scan.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setFormat("正在扫描... %p%")
        self.status_bar.showMessage("扫描进行中，请稍候...")
        
        # 传入 include_exts
        self.scanner = FileScanner(self.target_paths, is_incremental=is_incremental, include_exts=include_exts)
        self.scanner.start()

    def _on_stop_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.status_bar.showMessage("正在停止扫描...")

    def _on_scan_progress(self, current: int, total: int, current_path: str):
        self.progress_bar.setMaximum(0)
        short_path = current_path if len(current_path) < 60 else "..." + current_path[-57:]
        self.status_bar.showMessage(f"已扫描: {current} 个文件 | 当前: {short_path}")

    def _on_scan_finished(self, added: int, updated: int):
        self.btn_start_scan.setEnabled(True)
        self.btn_stop_scan.setEnabled(False)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("扫描完成！")
        self.status_bar.showMessage(f"扫描结束。新增 {added} 个，更新 {updated} 个。")
        QMessageBox.information(self, "扫描完成", f"扫描结束！\n新增: {added}\n更新: {updated}")

    def _on_operation_result(self, op_type: str, success: bool, message: str):
        color = "green" if success else "red"
        self.status_bar.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.status_bar.showMessage(f"[{op_type.upper()}] {message}", 5000)

    def _on_nav_changed(self, index: int):
        if index >= 0:
            self.stack.setCurrentIndex(index)