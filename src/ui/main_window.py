# === 文件路径: src/ui/main_window.py ===
"""主窗口骨架：菜单栏 + 分组工具栏 + 中央展示区 + 可停靠面板 + 状态栏。

布局由 framework/registry 驱动；面板可浮动/拖靠/合并，布局与主题持久化到 settings 表。
"""
from __future__ import annotations

import logging
import os
import re
import threading

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QSystemTrayIcon, QTabWidget, QToolBar,
)

from src import config
from src.config import FILE_TYPE_PRESETS
from src.core import exporter
from src.core.consolidation import ConsolidationService
from src.core.file_service import FileService
from src.core.meta_extractor import MetadataExtractor
from src.core.scanner import FileScanner
from src.core.vault import VaultService
from src.db.dao import ConsolidatedLinkDAO, FileDAO, TagDAO, SettingsDAO, VaultDAO
from src.db.database import DatabaseManager
from src.ui import icons, themes
from src.ui.framework.panel_base import PanelBase
from src.ui.framework.registry import PanelContext, iter_specs
from src.ui.icons import get_icon
from src.ui.panels.file_list_panel import FileListPanel
from src.ui.qt_bridge import get_bridge

logger = logging.getLogger(__name__)

SETTING_GEOMETRY = "window_geometry"
SETTING_LAYOUT = "layout_state"
SETTING_THEME = "theme"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileMaster - 智能文件管家 v2.0")
        self.resize(1280, 760)
        self.setMinimumSize(900, 600)

        # ---- core 层 ----
        self.db_manager = DatabaseManager()
        self.file_dao = FileDAO(self.db_manager)
        self.tag_dao = TagDAO(self.db_manager)
        self.settings_dao = SettingsDAO(self.db_manager)
        self.file_service = FileService(self.file_dao, self.tag_dao)
        self.bridge = get_bridge()

        self.scanner: FileScanner | None = None
        self.meta_extractor: MetadataExtractor | None = None
        self.target_paths: list[str] = []
        self._panels: dict[str, PanelBase] = {}
        self._icon_actions: list[tuple[QAction, str]] = []
        self.vault_service: VaultService | None = None

        # ---- 主题须先于构建界面生效，图标颜色才正确 ----
        self._theme = self.settings_dao.get_setting(SETTING_THEME, themes.palette.DEFAULT_THEME)
        if self._theme not in themes.palette.THEMES:
            self._theme = themes.palette.DEFAULT_THEME
        themes.apply_theme(QApplication.instance(), self._theme)

        self._init_window_shell()
        self._init_central()
        self._init_docks()
        self._init_menus()
        self._init_toolbar()
        self._init_statusbar()
        self._bind_signals()
        self._restore_layout()
        self._quitting = False
        self._init_tray()

    # ==========================================================
    # 骨架
    # ==========================================================
    def _init_window_shell(self) -> None:
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.GroupedDragging
        )
        self.setTabPosition(
            Qt.TopDockWidgetArea | Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea,
            QTabWidget.North,
        )
        # 底部停靠区的页签放到下沿，避免压住中央展示区底部的分页栏
        self.setTabPosition(Qt.BottomDockWidgetArea, QTabWidget.South)
        # 左下角归属左侧停靠区，避免底部面板的页签压住左栏
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)

    def _init_central(self) -> None:
        """中央展示区：文件列表，唯一中央部件，不可关闭/不可停靠。"""
        self.central_panel = FileListPanel(self.db_manager, self.file_service)
        self.setCentralWidget(self.central_panel)

    def _init_docks(self) -> None:
        ctx = PanelContext(db_manager=self.db_manager, file_service=self.file_service)

        for spec in iter_specs():
            content = spec.factory(ctx)
            panel = PanelBase(spec.panel_id, spec.title, content)
            panel.setObjectName(f"panel_{spec.panel_id}")
            self._panels[spec.panel_id] = panel
            self.addDockWidget(spec.area, panel)
            panel.closed_by_user.connect(self._on_panel_closed)

        # 同组面板合并为页签
        groups: dict[str, list[PanelBase]] = {}
        for spec in iter_specs():
            if spec.tab_group:
                groups.setdefault(spec.tab_group, []).append(self._panels[spec.panel_id])
        for panels in groups.values():
            for extra in panels[1:]:
                self.tabifyDockWidget(panels[0], extra)
            panels[0].raise_()

        # 面板内容引用（供主窗口内部联动）
        self.detail_widget = self._panels["detail"].widget()
        self.output_panel = self._panels["task_output"].widget()
        self.directory_panel = self._panels["directory_tree"].widget()
        self.query_builder_panel = self._panels["query_builder"].widget()

    # ==========================================================
    # 菜单
    # ==========================================================
    def _init_menus(self) -> None:
        bar = self.menuBar()

        # ---- 文件 ----
        m_file = bar.addMenu("文件(&F)")
        self.act_select_path = self._add_action(
            m_file, "选择扫描路径…", "fa5s.folder-open", self._on_select_path, QKeySequence("Ctrl+O"))
        self.act_start_scan = self._add_action(
            m_file, "开始扫描", "fa5s.play", self._on_start_scan, QKeySequence("F5"))
        self.act_stop_scan = self._add_action(
            m_file, "停止扫描", "fa5s.stop", self._on_stop_scan, QKeySequence("Shift+F5"))
        self.act_stop_scan.setEnabled(False)
        m_file.addSeparator()
        self._add_action(m_file, "打开数据目录", "fa5s.hdd", self._on_open_data_dir)
        m_file.addSeparator()
        self._add_action(m_file, "退出", "fa5s.sign-out-alt", self._real_quit, QKeySequence("Ctrl+Q"))

        # ---- 视图：面板开关由注册表自动生成 ----
        m_view = bar.addMenu("视图(&V)")
        for spec in iter_specs():
            panel = self._panels[spec.panel_id]
            act = panel.toggleViewAction()
            act.setText(spec.menu_text)
            act.setIcon(get_icon(spec.icon))
            if spec.shortcut:
                act.setShortcut(QKeySequence(spec.shortcut))
            m_view.addAction(act)
            self._icon_actions.append((act, spec.icon))

        m_view.addSeparator()
        self._add_action(m_view, "重置默认布局", "fa5s.undo", self._on_reset_layout)

        m_theme = m_view.addMenu("主题")
        m_theme.setIcon(get_icon("fa5s.palette"))
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self.act_theme_dark = self._add_theme_action(m_theme, "暗色（默认）", "dark")
        self.act_theme_light = self._add_theme_action(m_theme, "亮色", "light")
        (self.act_theme_dark if self._theme == "dark" else self.act_theme_light).setChecked(True)

        # ---- 工具 ----
        m_tools = bar.addMenu("工具(&T)")
        self._add_action(m_tools, "重复文件清理", "fa5s.copy",
                         lambda: self._show_panel("duplicates"))
        self._add_action(m_tools, "标签管理", "fa5s.tags",
                         lambda: self._show_panel("file_tags"))
        self._add_action(m_tools, "目录浏览", "fa5s.sitemap",
                         lambda: self._show_panel("directory_tree"))
        m_tools.addSeparator()
        self._add_action(m_tools, "自动标签规则…", "fa5s.magic", self._on_auto_rules)
        self._add_action(m_tools, "提取元数据", "fa5s.photo-video", self._on_extract_meta)
        self._add_action(m_tools, "清理失联索引…", "fa5s.broom", self._on_clear_missing)
        self._add_action(m_tools, "加密保险库…", "fa5s.lock", self._on_vault)
        m_tools.addSeparator()
        self._add_action(m_tools, "归集到…", "fa5s.object-group", self._on_consolidate)
        self._add_action(m_tools, "修复归集链接", "fa5s.link", self._on_repair_links)
        self._add_action(m_tools, "导出 CSV…", "fa5s.file-csv", self._on_export_csv)

        # ---- 设置 ----
        m_settings = bar.addMenu("设置(&S)")
        self._add_action(m_settings, "数据目录…", "fa5s.database", self._on_data_dir_settings)

        # ---- 帮助 ----
        m_help = bar.addMenu("帮助(&H)")
        self._add_action(m_help, "关于 FileMaster", "fa5s.question-circle", self._on_about)

    def _add_action(self, menu: QMenu, text: str, icon_name: str, slot,
                    shortcut: QKeySequence | None = None) -> QAction:
        act = QAction(text, self)
        if icon_name:
            act.setIcon(get_icon(icon_name))
            self._icon_actions.append((act, icon_name))
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _add_theme_action(self, menu: QMenu, text: str, theme: str) -> QAction:
        act = QAction(text, self)
        act.setCheckable(True)
        act.triggered.connect(lambda checked=False: self._set_theme(theme))
        self._theme_group.addAction(act)
        menu.addAction(act)
        return act

    # ==========================================================
    # 工具栏
    # ==========================================================
    def _init_toolbar(self) -> None:
        tb = QToolBar("主工具栏", self)
        tb.setObjectName("mainToolBar")
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setMovable(True)
        self.addToolBar(Qt.TopToolBarArea, tb)

        tb.addAction(self.act_select_path)
        tb.addAction(self.act_start_scan)
        tb.addAction(self.act_stop_scan)
        tb.addSeparator()

        tb.addWidget(QLabel(" 扫描类型: "))
        self.combo_scan_type = QComboBox(self)
        self.combo_scan_type.setEditable(True)
        self.combo_scan_type.addItems(FILE_TYPE_PRESETS)
        self.combo_scan_type.setFixedWidth(190)
        tb.addWidget(self.combo_scan_type)

        self.chk_incremental = QCheckBox("增量扫描", self)
        self.chk_incremental.setChecked(True)
        self.chk_incremental.setContentsMargins(6, 0, 6, 0)
        tb.addWidget(self.chk_incremental)
        tb.addSeparator()

        # 面板开关组
        for spec in iter_specs():
            act = self._panels[spec.panel_id].toggleViewAction()
            tb.addAction(act)

        tb.addSeparator()
        self.act_toggle_theme = QAction(get_icon("fa5s.adjust"), "切换主题", self)
        self.act_toggle_theme.setToolTip("在暗色/亮色主题间切换")
        self.act_toggle_theme.triggered.connect(
            lambda: self._set_theme("light" if self._theme == "dark" else "dark"))
        tb.addAction(self.act_toggle_theme)

        tb.addSeparator()
        self.act_lan_server = QAction("服务", self)
        self.act_lan_server.triggered.connect(self._on_toggle_lan_server)
        tb.addAction(self.act_lan_server)
        self._refresh_lan_action()

        self.main_toolbar = tb

    # ==========================================================
    # 状态栏
    # ==========================================================
    def _init_statusbar(self) -> None:
        bar = self.statusBar()
        bar.showMessage("就绪")

        self.lbl_total = QLabel("共 0 个文件")
        self.lbl_total.setProperty("role", "muted")
        bar.addPermanentWidget(self.lbl_total)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setMaximumHeight(16)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("就绪")
        self.progress_bar.setValue(0)
        bar.addPermanentWidget(self.progress_bar)

        self._refresh_total_count()

    def _refresh_total_count(self) -> None:
        try:
            _, total = self.file_dao.get_files_page(1, 1)
            missing = self.file_dao.count_missing()
            text = f"共 {total} 个文件"
            if missing:
                text += f" · 失联 {missing}"
            self.lbl_total.setText(text)
        except Exception:
            logger.exception("统计文件总数失败")

    # ==========================================================
    # 信号
    # ==========================================================
    def _bind_signals(self) -> None:
        self.bridge.scan_progress.connect(self._on_scan_progress)
        self.bridge.scan_finished.connect(self._on_scan_finished)
        self.bridge.meta_progress.connect(self._on_meta_progress)
        self.bridge.meta_finished.connect(self._on_meta_finished)
        self.bridge.file_operation_result.connect(self._on_operation_result)
        self.bridge.data_changed.connect(self._refresh_total_count)
        self.bridge.file_selected.connect(self.detail_widget.update_detail)
        # 详情面板左键双击预览图 → 复用文件列表的图片查看器（全局连续切换）
        self.detail_widget.set_image_viewer_opener(self.central_panel.open_image_viewer)

        self.directory_panel.path_selected.connect(self._set_scan_target)
        self.directory_panel.scan_requested.connect(self._on_directory_scan_requested)
        self.query_builder_panel.query_requested.connect(self.central_panel.load_tag_query_results)

    # ==========================================================
    # 扫描
    # ==========================================================
    def _set_scan_target(self, path: str) -> None:
        self.target_paths = [path]
        self.statusBar().showMessage(f"扫描目标：{path}", 5000)
        self.output_panel.append_message(f"扫描目标设为 {path}")

    def _on_directory_scan_requested(self, path: str) -> None:
        self._set_scan_target(path)
        self._on_start_scan()

    def _on_select_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要扫描的文件夹")
        if not path:
            return
        self._set_scan_target(path)
        if hasattr(self.directory_panel, "select_path"):
            self.directory_panel.select_path(path)

    def _parse_include_exts(self, type_str: str) -> set[str] | None:
        if not type_str or type_str == "全部":
            return None
        match = re.search(r"\((.*?)\)", type_str)
        raw = match.group(1) if match else type_str
        exts = {e.strip().lstrip("*").lower() for e in re.split(r"[,\s;]+", raw) if e.strip()}
        return exts or None

    def _on_start_scan(self) -> None:
        if self.scanner and self.scanner.is_alive():
            QMessageBox.information(self, "提示", "扫描正在进行中。")
            return
        if not self.target_paths:
            QMessageBox.warning(self, "提示", "请先在左侧目录树双击选择目录，或使用「文件 → 选择扫描路径」。")
            return

        include_exts = self._parse_include_exts(self.combo_scan_type.currentText().strip())
        is_incremental = self.chk_incremental.isChecked()

        self.act_start_scan.setEnabled(False)
        self.act_stop_scan.setEnabled(True)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setFormat("扫描中…")
        self.statusBar().showMessage("扫描进行中…")
        self.output_panel.append_message(f"开始扫描：{', '.join(self.target_paths)}")

        self.scanner = FileScanner(
            self.target_paths,
            is_incremental=is_incremental,
            include_exts=include_exts,
            on_progress=self.bridge.scan_progress.emit,
            on_finished=self.bridge.scan_finished.emit,
        )
        self.scanner.start()

    def _on_stop_scan(self) -> None:
        if self.scanner and self.scanner.is_alive():
            self.scanner.stop()
            self.statusBar().showMessage("正在停止扫描…")
            self.output_panel.append_message("已请求停止扫描")

    def _on_scan_progress(self, current: int, total: int, current_path: str) -> None:
        short = current_path if len(current_path) < 70 else "…" + current_path[-68:]
        self.statusBar().showMessage(f"已处理 {current} 个文件 | {short}")
        if current % 200 == 0:
            self.output_panel.append_message(f"已处理 {current} 个文件")

    def _on_scan_finished(self, added: int, updated: int) -> None:
        self.act_start_scan.setEnabled(True)
        self.act_stop_scan.setEnabled(False)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("扫描完成")
        missing = self.file_dao.count_missing()
        summary = f"新增 {added}，更新 {updated}"
        if missing:
            summary += f"，失联 {missing}"
        self.statusBar().showMessage(f"扫描结束：{summary}", 10000)
        self.output_panel.append_message(f"扫描结束：{summary}")
        self._refresh_total_count()
        self._start_meta_extraction()

    def _on_operation_result(self, op_type: str, success: bool, message: str) -> None:
        self.output_panel.append_message(f"[{op_type}] {message}", "info" if success else "error")
        self.statusBar().showMessage(f"[{op_type}] {message}", 5000)

    # ==========================================================
    # 元数据提取
    # ==========================================================
    def _start_meta_extraction(self) -> None:
        if self.meta_extractor and self.meta_extractor.is_alive():
            return
        pending = self.file_dao.count_pending_meta()
        if not pending:
            return
        self.output_panel.append_message(f"开始提取元数据（待处理 {pending} 个文件）")
        self.meta_extractor = MetadataExtractor(
            self.file_dao,
            on_progress=self.bridge.meta_progress.emit,
            on_finished=self.bridge.meta_finished.emit,
        )
        self.meta_extractor.start()

    def _on_extract_meta(self) -> None:
        pending = self.file_dao.count_pending_meta()
        if not pending:
            QMessageBox.information(self, "提取元数据", "所有媒体文件的元数据都已是最新。")
            return
        self._start_meta_extraction()

    def _on_meta_progress(self, current: int, total: int, path: str) -> None:
        self.statusBar().showMessage(f"提取元数据 {current}/{total} | {os.path.basename(path)}")

    def _on_meta_finished(self, succeeded: int, failed: int) -> None:
        self.output_panel.append_message(f"元数据提取完成：成功 {succeeded}，跳过/失败 {failed}")
        self.statusBar().showMessage(f"元数据提取完成：成功 {succeeded}", 5000)
        self.bridge.data_changed.emit()

    def _on_panel_closed(self, panel_id: str) -> None:
        self.output_panel.append_message(f"面板已关闭：{panel_id}（可从「视图」菜单重新打开）")

    # ==========================================================
    # 面板 / 主题 / 布局
    # ==========================================================
    def _show_panel(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is None:
            return
        panel.show()
        panel.raise_()
        panel.setFloating(False)
        panel.toggleViewAction().setChecked(True)

    def _set_theme(self, theme: str) -> None:
        self._theme = theme
        themes.apply_theme(QApplication.instance(), theme)
        icons.refresh()
        self._apply_icons()
        self.settings_dao.set_setting(SETTING_THEME, theme)
        (self.act_theme_dark if theme == "dark" else self.act_theme_light).setChecked(True)
        self.output_panel.append_message(f"主题已切换为 {theme}")

    def _apply_icons(self) -> None:
        for act, icon_name in self._icon_actions:
            act.setIcon(get_icon(icon_name))
        self.act_toggle_theme.setIcon(get_icon("fa5s.adjust"))
        for panel in self._panels.values():
            panel.refresh_icons()

    def _apply_default_layout(self) -> None:
        for spec in iter_specs():
            panel = self._panels[spec.panel_id]
            panel.setFloating(False)
            panel.show()
            self.addDockWidget(spec.area, panel)

        groups: dict[str, list[PanelBase]] = {}
        for spec in iter_specs():
            if spec.tab_group:
                groups.setdefault(spec.tab_group, []).append(self._panels[spec.panel_id])
        for panels in groups.values():
            for extra in panels[1:]:
                self.tabifyDockWidget(panels[0], extra)
            panels[0].raise_()

        self.resizeDocks([self._panels["directory_tree"]], [180], Qt.Horizontal)
        self.resizeDocks(
            [self._panels["file_tags"], self._panels["detail"]], [340, 340], Qt.Horizontal)
        self.resizeDocks(
            [self._panels["duplicates"], self._panels["task_output"]], [210, 210], Qt.Vertical)

    def _restore_layout(self) -> None:
        restored = False
        state_b64 = self.settings_dao.get_setting(SETTING_LAYOUT)
        if state_b64:
            try:
                restored = self.restoreState(QByteArray.fromBase64(state_b64.encode()))
            except Exception:
                logger.exception("恢复布局失败，回退默认布局")
        if not restored:
            self._apply_default_layout()

        geo_b64 = self.settings_dao.get_setting(SETTING_GEOMETRY)
        if geo_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo_b64.encode()))
            except Exception:
                logger.exception("恢复窗口几何失败")

    def _save_layout(self) -> None:
        try:
            self.settings_dao.set_setting(
                SETTING_LAYOUT, bytes(self.saveState().toBase64()).decode())
            self.settings_dao.set_setting(
                SETTING_GEOMETRY, bytes(self.saveGeometry().toBase64()).decode())
        except Exception:
            logger.exception("保存布局失败")

    def _on_reset_layout(self) -> None:
        if QMessageBox.question(self, "重置布局", "确定要恢复默认面板布局吗？") != QMessageBox.Yes:
            return
        self._apply_default_layout()
        self.settings_dao.set_setting(SETTING_LAYOUT, "")
        self.output_panel.append_message("面板布局已重置为默认")

    # ==========================================================
    # 设置 / 帮助
    # ==========================================================
    def _on_auto_rules(self) -> None:
        from src.ui.dialogs.auto_rule_dialog import AutoRuleDialog
        dialog = AutoRuleDialog(self.db_manager, self)
        dialog.exec()
        self.bridge.data_changed.emit()

    def _on_vault(self) -> None:
        from src.ui.dialogs.lock_dialog import LockDialog
        from src.ui.dialogs.vault_dialog import VaultDialog
        if self.vault_service is None:
            self.vault_service = VaultService(
                self.db_manager, self.settings_dao, VaultDAO(self.db_manager),
                config.VAULT_DIR,
            )
        if not LockDialog.run(self.vault_service, self):
            return
        dialog = VaultDialog(self.vault_service, self)
        dialog.exec()

    def start_lan_server(self, port: int) -> tuple[bool, str]:
        """启动局域网服务。返回 (是否成功, 消息/地址)。供设置对话框/工具栏调用。"""
        from src.server.lan_server import LanServer
        from src.core.vault import VaultService
        from src.db.dao import VaultDAO

        existing = getattr(self, "_lan_server", None)
        if existing is not None and existing.is_running:
            return True, existing.access_url()

        if self.vault_service is None:
            self.vault_service = VaultService(
                self.db_manager, self.settings_dao, VaultDAO(self.db_manager),
                config.VAULT_DIR,
            )
        if not self.vault_service.is_lock_enabled():
            return False, "请先在「安全 → 修改主密码」中设置主密码（可设为空）"

        server = LanServer(self.db_manager, self.file_service, self.vault_service, port=port)
        try:
            server.start()
        except OSError:
            return False, f"端口 {port} 被占用或不可用"
        self._lan_server = server
        url = server.access_url()
        self.statusBar().showMessage(f"局域网服务运行中: {url}", 10000)
        self._refresh_lan_action()
        return True, url

    def stop_lan_server(self) -> None:
        """停止局域网服务（若运行中）。供设置对话框/工具栏/退出时调用。"""
        server = getattr(self, "_lan_server", None)
        if server is not None:
            server.stop()
            self._lan_server = None
            self.statusBar().showMessage("局域网服务已停止", 5000)
            self._refresh_lan_action()

    def lan_server_url(self) -> str | None:
        """运行中返回访问地址，否则 None。"""
        server = getattr(self, "_lan_server", None)
        return server.access_url() if server is not None and server.is_running else None

    def _refresh_lan_action(self) -> None:
        """按服务实际状态刷新工具栏服务按钮（绿色=运行中，灰色=已停止）。

        启停无论来自工具栏还是设置对话框都经过 start/stop_lan_server，
        在此统一刷新即可保证两处状态同步。
        """
        if not hasattr(self, "act_lan_server"):
            return
        url = self.lan_server_url()
        if url:
            self.act_lan_server.setIcon(get_icon("fa5s.broadcast-tower", "#3fb950"))
            self.act_lan_server.setText("服务·运行中")
            self.act_lan_server.setToolTip(f"局域网服务运行中：{url}\n点击停止")
        else:
            self.act_lan_server.setIcon(get_icon("fa5s.broadcast-tower", "#9aa0a6"))
            self.act_lan_server.setText("服务·已停止")
            self.act_lan_server.setToolTip("启动局域网服务，手机浏览器访问（点击启动）")
        self._refresh_tray_lan_action()

    def _on_toggle_lan_server(self) -> None:
        """工具栏服务按钮：运行中则停止，否则按设置里保存的端口启动。"""
        if self.lan_server_url():
            self.stop_lan_server()
            return
        from src.ui.dialogs.settings_dialog import SETTING_LAN_PORT, DEFAULT_LAN_PORT
        raw = self.settings_dao.get_setting(SETTING_LAN_PORT, str(DEFAULT_LAN_PORT))
        try:
            port = int(raw)
            if not 1024 <= port <= 65535:
                port = DEFAULT_LAN_PORT
        except (TypeError, ValueError):
            port = DEFAULT_LAN_PORT
        ok, msg = self.start_lan_server(port)
        if not ok:
            QMessageBox.warning(self, "局域网服务", f"启动失败：{msg}")

    def _on_clear_missing(self) -> None:
        count = self.file_dao.count_missing()
        if not count:
            QMessageBox.information(self, "清理失联索引", "当前没有失联记录。")
            return
        answer = QMessageBox.question(
            self, "清理失联索引",
            f"将从索引中删除 {count} 条失联记录（不会删除磁盘上的任何文件）。\n确定继续吗？",
        )
        if answer != QMessageBox.Yes:
            return
        removed = self.file_dao.clear_missing()
        self.bridge.data_changed.emit()
        self.output_panel.append_message(f"已清理 {removed} 条失联索引")

    # ==========================================================
    # 归集 / CSV 导出（M5）
    # ==========================================================
    def _gather_current_records(self) -> list:
        """按中央列表当前筛选取全量记录（含标签展示字段）。"""
        filters = self.central_panel.current_filters()
        records, _ = self.file_dao.get_files_page(1, 10 ** 7, **filters)
        for record in records:
            record.tags_str = self.file_dao.get_file_tags_str(record.id)
        return records

    def _consolidation_service(self) -> ConsolidationService:
        if not hasattr(self, "_consolidation_svc"):
            self._consolidation_svc = ConsolidationService(
                self.file_dao, ConsolidatedLinkDAO(self.db_manager))
        return self._consolidation_svc

    def _on_consolidate(self) -> None:
        if getattr(self, "_consolidate_worker", None) and self._consolidate_worker.is_alive():
            QMessageBox.information(self, "归集", "归集任务正在进行中。")
            return
        target = QFileDialog.getExistingDirectory(self, "选择归集目标目录")
        if not target:
            return
        records = self._gather_current_records()
        if not records:
            QMessageBox.information(self, "归集", "当前筛选没有可归集的记录。")
            return
        answer = QMessageBox.question(
            self, "归集到",
            f"将把 {len(records)} 条记录按「大类/年份」硬链接收拢到：\n{target}\n"
            "（跨卷时自动回退为复制，不移动、不删除原文件）\n确定继续吗？",
        )
        if answer != QMessageBox.Yes:
            return

        svc = self._consolidation_service()
        bridge = self.bridge

        def worker() -> None:
            result = svc.consolidate(records, target)
            bridge.file_operation_result.emit(
                "归集", result.ok, f"{result.summary()} → {target}")
            bridge.data_changed.emit()

        self._consolidate_worker = threading.Thread(target=worker, daemon=True)
        self._consolidate_worker.start()
        self.statusBar().showMessage(f"归集进行中 → {target}")

    def _on_repair_links(self) -> None:
        if getattr(self, "_consolidate_worker", None) and self._consolidate_worker.is_alive():
            QMessageBox.information(self, "修复归集链接", "归集任务正在进行中。")
            return
        svc = self._consolidation_service()
        bridge = self.bridge

        def worker() -> None:
            result = svc.repair_links()
            bridge.file_operation_result.emit(
                "修复归集链接", result.ok, result.summary())
            bridge.data_changed.emit()

        self._consolidate_worker = threading.Thread(target=worker, daemon=True)
        self._consolidate_worker.start()
        self.statusBar().showMessage("正在修复归集链接…")

    def _on_export_csv(self) -> None:
        out, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", exporter.default_csv_name(), "CSV 文件 (*.csv)")
        if not out:
            return
        records = self._gather_current_records()
        if not records:
            QMessageBox.information(self, "导出 CSV", "当前筛选没有可导出的记录。")
            return
        dest = exporter.export_csv(records, out)
        self.output_panel.append_message(f"已导出 {len(records)} 条记录 → {dest}")
        QMessageBox.information(self, "导出 CSV", f"已导出 {len(records)} 条记录到：\n{dest}")

    def _on_open_data_dir(self) -> None:
        os.startfile(str(config.APPDATA_DIR))

    def _on_data_dir_settings(self) -> None:
        from src.ui.dialogs.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, self.db_manager)
        dialog.exec()

    def stop_background_tasks(self) -> None:
        """停止全部后台线程（扫描/元数据/缩略图），等待退出。"""
        if self.scanner and self.scanner.is_alive():
            self.scanner.stop()
            self.scanner.join(2)
        if self.meta_extractor and self.meta_extractor.is_alive():
            self.meta_extractor.stop()
            self.meta_extractor.join(2)
        thumb_manager = getattr(self.central_panel, "thumb_manager", None)
        if thumb_manager and thumb_manager.is_alive():
            thumb_manager.stop()
            thumb_manager.join(2)

    def _on_about(self) -> None:
        from src.ui.dialogs.about_dialog import AboutDialog
        AboutDialog(self).exec()

    # ==========================================================
    # 系统托盘
    # ==========================================================
    def _init_tray(self) -> None:
        """创建托盘图标：单击恢复窗口；右键菜单可显示窗口或退出。

        关闭窗口仅最小化到托盘（局域网服务保持运行），真正退出走 _real_quit。
        """
        self._tray: QSystemTrayIcon | None = None
        self._tray_notified = False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("系统不支持托盘，跳过托盘图标创建")
            return

        menu = QMenu(self)
        act_show = menu.addAction(get_icon("fa5s.window-restore"), "显示主窗口")
        act_show.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        self.act_tray_lan = menu.addAction("局域网服务")
        self.act_tray_lan.triggered.connect(self._on_toggle_lan_server)
        menu.addSeparator()
        act_quit = menu.addAction(get_icon("fa5s.sign-out-alt"), "退出")
        act_quit.triggered.connect(self._real_quit)
        menu.aboutToShow.connect(self._refresh_tray_lan_action)

        self._tray = QSystemTrayIcon(get_icon("fa5s.folder-open", "#4c8dff"), self)
        self._tray.setToolTip("FileMaster 智能文件管家")
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        self._refresh_tray_lan_action()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_tray_lan_action(self) -> None:
        """按服务状态实时刷新托盘服务菜单项与托盘图标颜色。

        菜单打开前（aboutToShow）及每次启停后都会调用：
        运行中 → 绿色图标，停止 → 蓝/灰色图标，一眼可辨。
        """
        if getattr(self, "_tray", None) is None:
            return
        url = self.lan_server_url()
        if url:
            self.act_tray_lan.setIcon(get_icon("fa5s.broadcast-tower", "#3fb950"))
            self.act_tray_lan.setText("局域网服务：运行中（点击停止）")
            self.act_tray_lan.setToolTip(url)
            self._tray.setIcon(get_icon("fa5s.folder-open", "#3fb950"))
            self._tray.setToolTip(f"FileMaster 智能文件管家\n局域网服务运行中：{url}")
        else:
            self.act_tray_lan.setIcon(get_icon("fa5s.broadcast-tower", "#9aa0a6"))
            self.act_tray_lan.setText("局域网服务：已停止（点击启动）")
            self.act_tray_lan.setToolTip("启动后手机浏览器访问")
            self._tray.setIcon(get_icon("fa5s.folder-open", "#4c8dff"))
            self._tray.setToolTip("FileMaster 智能文件管家")

    def _real_quit(self) -> None:
        """真正退出：菜单「退出」/托盘「退出」入口。

        窗口处于隐藏态（最小化到托盘）时仅 close() 不会让应用退出
        （托盘图标仍存活），必须显式退出事件循环。
        """
        self._quitting = True
        self.close()
        QApplication.quit()

    # ==========================================================
    # 退出
    # ==========================================================
    def closeEvent(self, event) -> None:
        # 托盘可用且非真正退出时，关闭窗口仅最小化到托盘
        if self._tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_notified:
                self._tray_notified = True
                self._tray.showMessage(
                    "FileMaster", "程序已最小化到托盘，右键托盘图标可退出",
                    QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        self.stop_lan_server()
        self.stop_background_tasks()
        self._save_layout()
        logger.info("Main window closed, layout saved.")
        super().closeEvent(event)
