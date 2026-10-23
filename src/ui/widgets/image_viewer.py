# === 文件路径: src/ui/widgets/image_viewer.py ===
from __future__ import annotations
import os
import shutil
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QLabel, QPushButton, QWidget,
    QMenu, QFileDialog, QMessageBox,
)
from PySide6.QtGui import QPixmap, QWheelEvent, QPainter, QColor
from PySide6.QtCore import Qt, QSize, QEvent, Signal, QPropertyAnimation, QEasingCurve

from src.ui.icons import get_icon
from src.ui import themes
from src.core.file_service import STRATEGY_RENAME

# 窗口占屏幕可用区域的比例（窗口固定，图片自适应窗口）
_SCREEN_RATIO = 0.85
# 左右悬浮切换按钮尺寸
_NAV_BTN_W = 44
_NAV_BTN_H = 64
_NAV_BTN_MARGIN = 10
# 底部标签抽拉面板展开高度
_TAG_DRAWER_H = 240
# 标签 chip 最多显示个数，超出以 "+N" 表示
_MAX_TAG_CHIPS = 10

# 边界回调返回类型
_BoundaryCallback = "callable[[str], tuple[list[str], int] | None]"


def _is_link(path: str) -> bool:
    """是否为符号链接或 Windows 目录联结（junction），二者都只能删除链接本身。"""
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    return bool(is_junction and is_junction(path))


def _remove_link(path: str) -> None:
    """删除链接本身，绝不跟随链接目标（Windows 目录链接需用 rmdir）。"""
    try:
        os.remove(path)
    except (IsADirectoryError, PermissionError):
        # Windows 下目录符号链接/junction 不能用 RemoveFile 删除
        os.rmdir(path)


def _clear_dir_contents(target_dir: str) -> None:
    """清空文件夹内的全部内容（保留文件夹本身），链接只删链接、不清理其目标。"""
    for entry in os.listdir(target_dir):
        entry_path = os.path.join(target_dir, entry)
        if _is_link(entry_path):
            _remove_link(entry_path)
        elif os.path.isdir(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)


class ImageViewer(QDialog):
    """
    图片查看器：窗口固定（屏幕 85%），图片在窗口内自适应缩放；
    左右两侧垂直居中悬浮图标按钮切换上一张/下一张；
    支持滚轮缩放、拖拽平移、双击恢复自适应；
    支持通过回调跨页翻页（全局查询结果内连续切换）；
    底部标签栏：显示当前图片标签，支持编辑（依赖注入，缺省时自动隐藏）。
    """

    # 标签被修改后发出，供主界面刷新列表/详情中的标签列
    tags_changed = Signal()
    # 文件数据被修改（重命名/移动/删除等）后发出，供主界面刷新列表
    data_changed = Signal()

    def __init__(
        self,
        image_path: str,
        parent=None,
        image_list: list[str] | None = None,
        on_boundary_reached: _BoundaryCallback | None = None,
        file_dao=None,
        tag_dao=None,
        file_service=None,
    ):
        super().__init__(parent)
        # 仅作为普通顶层窗口：exec() 模态已保证盖在主窗口上；
        # 不做系统级置顶，避免右键“打开文件目录”后遮挡资源管理器等外部窗口
        self.setWindowFlags(Qt.Window)

        # 主题色：与全局主题联动（viewer 为模态，打开期间主题不会变，构造时取一次即可）
        c = themes.palette.colors(themes.current_theme())
        nav_bg = QColor(c["surface_alt"]); nav_bg.setAlpha(160)
        nav_bg_hover = QColor(c["surface_hover"]); nav_bg_hover.setAlpha(220)
        nav_bg_disabled = QColor(c["surface_alt"]); nav_bg_disabled.setAlpha(60)

        # 图片列表与当前索引（单张时列表只含自身，切换按钮自动隐藏）
        self._image_list: list[str] = list(image_list) if image_list else [image_path]
        if image_path in self._image_list:
            self._index = self._image_list.index(image_path)
        else:
            self._image_list.insert(0, image_path)
            self._index = 0

        # 跨页翻页回调：direction='prev'|'next'，返回 (new_list, new_index) 或 None
        self._on_boundary = on_boundary_reached

        # 标签功能依赖（三者齐备才启用标签栏）
        self._file_dao = file_dao
        self._tag_dao = tag_dao
        self._file_service = file_service
        self._tags_enabled = all(x is not None for x in (file_dao, tag_dao, file_service))

        # 清空目标文件夹确认弹窗：本次打开期间勾选“记住”后不再重复确认
        self._skip_clear_confirm = False

        self.item: QGraphicsPixmapItem | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 图形视图
        self.view = QGraphicsView(self)
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        # 图片查看器不需要滚动条：拖拽平移 + 滚轮缩放已覆盖导航需求
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 图片小于视口时上下左右居中显示
        self.view.setAlignment(Qt.AlignCenter)
        # 与全局主题联动：视口背景跟随当前主题 bg 色
        self.view.setBackgroundBrush(QColor(c["bg"]))
        # 去掉默认的凹陷边框（默认 StyledPanel 会让图片区看起来多套了一层框）
        self.view.setFrameShape(QGraphicsView.NoFrame)
        # 完全接管滚轮：拦截 QGraphicsView 默认的滚动行为，只保留缩放
        self.view.viewport().installEventFilter(self)
        layout.addWidget(self.view, 1)

        # 加载失败提示（与视图互斥显示）
        self.error_label = QLabel(self)
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {c['text']}; font-size: 14px; padding: 24px;")
        self.error_label.hide()
        layout.addWidget(self.error_label, 1)

        # 底部标签栏：chips 横排 + 编辑按钮（依赖齐全才显示）
        self.tag_bar = QWidget(self)
        tag_layout = QHBoxLayout(self.tag_bar)
        tag_layout.setContentsMargins(10, 4, 8, 4)
        tag_layout.setSpacing(6)
        self.tag_bar.setStyleSheet(f"background-color: {c['surface']};")

        tag_title = QLabel("标签:")
        tag_title.setStyleSheet(f"color: {c['text_muted']}; font-size: 12px; background: transparent;")
        tag_layout.addWidget(tag_title)

        # chips 容器（横排，多标签不换行，超出以 "+N" 收尾）
        self.chips_container = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(4)
        tag_layout.addWidget(self.chips_container, 1)

        # chip / 无标签提示样式（保存供 _refresh_tags 复用）
        self._chip_style = (
            f"QPushButton {{ background: {c['surface_alt']}; color: {c['text']};"
            f" border: 1px solid {c['border']}; border-radius: 10px; padding: 1px 10px; }}"
            f"QPushButton:hover {{ background: {c['surface_hover']}; }}"
        )
        self._chip_more_style = f"color: {c['text_muted']}; font-size: 12px; background: transparent;"

        self.btn_edit_tags = QPushButton("编辑标签 (T)")
        self.btn_edit_tags.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: {c['accent_text']}; border: none;"
            f" border-radius: 4px; padding: 3px 12px; }}"
            f"QPushButton:hover {{ background: {c['accent_hover']}; }}"
            f"QPushButton:disabled {{ background: {c['surface_hover']}; color: {c['text_muted']}; }}")
        self.btn_edit_tags.clicked.connect(self._edit_tags)
        tag_layout.addWidget(self.btn_edit_tags)

        if not self._tags_enabled:
            self.tag_bar.hide()
        layout.addWidget(self.tag_bar)

        # 底部抽拉式标签编辑面板（默认收起：高度 0，动画展开）
        self._drawer_open = False
        self.tag_drawer = QWidget(self)
        drawer_layout = QVBoxLayout(self.tag_drawer)
        drawer_layout.setContentsMargins(10, 6, 8, 8)
        drawer_layout.setSpacing(6)
        self.tag_drawer.setStyleSheet(
            f"background-color: {c['surface']}; border-top: 1px solid {c['border']};")

        # 面板标题行：标题 + 应用/收起按钮
        drawer_header = QHBoxLayout()
        drawer_header.setSpacing(8)
        drawer_title = QLabel("编辑标签")
        drawer_title.setStyleSheet(f"color: {c['text']}; font-weight: bold; background: transparent; border: none;")
        drawer_header.addWidget(drawer_title)
        drawer_header.addStretch()

        drawer_btn_style = (
            "QPushButton { border: none; border-radius: 4px; padding: 3px 14px; }"
        )
        self.btn_tag_apply = QPushButton("应用")
        self.btn_tag_apply.setStyleSheet(
            drawer_btn_style +
            f"QPushButton {{ background: {c['success']}; color: {c['accent_text']}; }}"
            f"QPushButton:hover {{ background: {c['success']}; opacity: 0.85; }}")
        self.btn_tag_apply.clicked.connect(self._apply_tags)
        drawer_header.addWidget(self.btn_tag_apply)

        self.btn_tag_close = QPushButton("收起")
        self.btn_tag_close.setStyleSheet(
            drawer_btn_style +
            f"QPushButton {{ background: {c['surface_hover']}; color: {c['text']}; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}")
        self.btn_tag_close.clicked.connect(lambda: self._toggle_drawer(False))
        drawer_header.addWidget(self.btn_tag_close)
        drawer_layout.addLayout(drawer_header)

        # 编辑区（复用 TagEditorWidget，与弹窗同一实现）
        if self._tags_enabled:
            from src.ui.widgets.tag_editor_widget import TagEditorWidget
            self.tag_editor = TagEditorWidget(self._tag_dao, self.tag_drawer)
            self.tag_editor.setStyleSheet("border: none;")
        else:
            self.tag_editor = None
        drawer_layout.addWidget(self.tag_editor, 1)

        self.tag_drawer.setMinimumHeight(0)
        self.tag_drawer.setMaximumHeight(0)
        self.tag_drawer.hide()
        layout.addWidget(self.tag_drawer)

        # 展开/收起动画
        self._drawer_anim = QPropertyAnimation(self.tag_drawer, b"maximumHeight", self)
        self._drawer_anim.setDuration(180)
        self._drawer_anim.setEasingCurve(QEasingCurve.OutCubic)

        # 左右悬浮切换按钮（图标，垂直居中，不参与布局）
        nav_style = f"""
            QPushButton {{
                background-color: rgba({nav_bg.red()}, {nav_bg.green()}, {nav_bg.blue()}, 160);
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{ background-color: rgba({nav_bg_hover.red()}, {nav_bg_hover.green()}, {nav_bg_hover.blue()}, 220); }}
            QPushButton:disabled {{ background-color: rgba({nav_bg_disabled.red()}, {nav_bg_disabled.green()}, {nav_bg_disabled.blue()}, 60); }}
        """
        self.btn_prev = QPushButton(self)
        self.btn_prev.setIcon(get_icon("fa5s.chevron-left"))
        self.btn_prev.setIconSize(QSize(20, 20))
        self.btn_prev.setFixedSize(_NAV_BTN_W, _NAV_BTN_H)
        self.btn_prev.setToolTip("上一张 (←)")
        self.btn_prev.setStyleSheet(nav_style)
        self.btn_prev.clicked.connect(self.show_prev)

        self.btn_next = QPushButton(self)
        self.btn_next.setIcon(get_icon("fa5s.chevron-right"))
        self.btn_next.setIconSize(QSize(20, 20))
        self.btn_next.setFixedSize(_NAV_BTN_W, _NAV_BTN_H)
        self.btn_next.setToolTip("下一张 (→)")
        self.btn_next.setStyleSheet(nav_style)
        self.btn_next.clicked.connect(self.show_next)

        self.btn_prev.raise_()
        self.btn_next.raise_()

        # 只有一张且不翻页时不显示切换按钮
        self._update_nav_buttons_visibility()

        # 窗口固定为屏幕的 85%，图片在窗口内自适应
        self._fit_window_to_screen()
        self._position_nav_buttons()
        self._load_current()

    # ---- 窗口与图片自适应 ----
    def showEvent(self, event):
        """首次显示时视口才有最终尺寸，此时做一次精确的自适应。"""
        super().showEvent(event)
        self._fit_and_center()

    def _fit_and_center(self):
        """图片自适应视口并居中。

        不用 fitInView：它内部只做增量缩放修正、不重置平移/滚动残留，
        拖拽或滚轮缩放后再切换图片会导致新图偏移不居中。
        这里显式约束 sceneRect、完全重置变换矩阵后重新计算缩放。
        """
        if self.item is None:
            return
        rect = self.item.boundingRect()
        # 显式约束场景范围为当前图片，清除上一张图的滚动范围残留
        self.scene.setSceneRect(rect)
        # 完全重置缩放/平移矩阵，消除拖拽、滚轮缩放后的残留状态
        self.view.resetTransform()
        viewport_rect = self.view.viewport().rect()
        if viewport_rect.isEmpty() or rect.isEmpty():
            return
        # 宽/高哪个相对视口更大，就以哪个方向为基准缩放
        ratio = min(viewport_rect.width() / rect.width(),
                    viewport_rect.height() / rect.height())
        self.view.scale(ratio, ratio)
        self.view.centerOn(rect.center())

    def _fit_window_to_screen(self):
        """窗口固定为屏幕可用区域的 85%（保持屏幕宽高比）。"""
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * _SCREEN_RATIO),
                    int(screen.height() * _SCREEN_RATIO))

    def _position_nav_buttons(self):
        """切换按钮定位到左右两侧、高度中间。"""
        y = (self.height() - _NAV_BTN_H) // 2
        self.btn_prev.move(_NAV_BTN_MARGIN, y)
        self.btn_next.move(self.width() - _NAV_BTN_W - _NAV_BTN_MARGIN, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口尺寸变化后重新自适应并居中
        self._fit_and_center()
        self._position_nav_buttons()

    # ---- 图片加载 ----
    def _load_current(self):
        path = self._image_list[self._index]
        self.setWindowTitle(
            f"图片预览 - {os.path.basename(path)} ({self._index + 1}/{len(self._image_list)})")
        self.scene.clear()
        self.item = None

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.error_label.hide()
            self.view.show()
            self.item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(self.item)
            # 图片自适应窗口并居中（重置式，清除上一张的残留状态）
            self._fit_and_center()
        else:
            # 文件存在但无法解码（被独占锁定 / 权限拒绝 / 文件损坏）
            self.view.hide()
            self.error_label.setText(
                f"🔒 图片加载失败\n\n文件：{path}\n\n"
                "可能原因：文件正被其他程序以独占模式锁定、无读取权限，或文件已损坏。")
            self.error_label.show()

        self._update_nav()
        self._refresh_tags()

    # ---- 标签 ----
    def _refresh_tags(self):
        """刷新底部标签栏：以 chip 按钮横排展示当前图片的标签。"""
        if not self._tags_enabled:
            return

        path = self._image_list[self._index]
        record = self._file_dao.get_file_by_path(path)

        # 清空旧 chips
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if record is None:
            lbl = QLabel("(文件未入库)")
            lbl.setStyleSheet(self._chip_more_style)
            self.chips_layout.addWidget(lbl)
            self.btn_edit_tags.setEnabled(False)
            if self._drawer_open:
                self._toggle_drawer(False)
            return

        names = [t.tag_name for t in self._tag_dao.get_tags_by_file_id(record.id)]
        if not names:
            lbl = QLabel("(无)")
            lbl.setStyleSheet(self._chip_more_style)
            self.chips_layout.addWidget(lbl)
        else:
            # 最多显示 _MAX_TAG_CHIPS 个，超出以 "+N" 收尾
            for name in names[:_MAX_TAG_CHIPS]:
                chip = QPushButton(name)
                chip.setStyleSheet(self._chip_style)
                chip.setFlat(False)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip("点击编辑标签")
                chip.setFocusPolicy(Qt.NoFocus)
                chip.clicked.connect(lambda _checked=False: self._edit_tags())
                self.chips_layout.addWidget(chip)
            if len(names) > _MAX_TAG_CHIPS:
                more = QLabel(f"+{len(names) - _MAX_TAG_CHIPS}")
                more.setStyleSheet(self._chip_more_style)
                more.setToolTip("、".join(names[_MAX_TAG_CHIPS:]))
                self.chips_layout.addWidget(more)
        self.chips_layout.addStretch()

        self.btn_edit_tags.setEnabled(True)
        # 抽拉面板开着时切换图片 → 编辑内容跟随当前图（未应用的勾选视为放弃）
        if self._drawer_open and self.tag_editor is not None:
            self.tag_editor.load_for_file(record.id)
            self.tag_editor.clear_new_input()

    # ---- 抽拉面板 ----
    def _toggle_drawer(self, open_: bool) -> None:
        """展开/收起底部标签编辑面板。"""
        if not self._tags_enabled:
            return
        if self._drawer_open == open_:
            return
        self._drawer_open = open_
        target = _TAG_DRAWER_H if open_ else 0
        self._drawer_anim.stop()
        # 避免 finished 信号随反复开关累积连接
        try:
            self._drawer_anim.finished.disconnect()
        except RuntimeError:
            pass
        self._drawer_anim.finished.connect(self._on_drawer_anim_finished)
        self._drawer_anim.setStartValue(self.tag_drawer.maximumHeight())
        self._drawer_anim.setEndValue(target)
        self.tag_drawer.setVisible(True)
        self._drawer_anim.start()
        self.btn_edit_tags.setText("关闭编辑 (T)" if open_ else "编辑标签 (T)")

    def _on_drawer_anim_finished(self):
        if not self._drawer_open:
            self.tag_drawer.hide()

    def _edit_tags(self) -> None:
        """切换底部标签编辑面板开关状态。"""
        if not self._tags_enabled:
            return
        if self._drawer_open:
            self._toggle_drawer(False)
            return
        path = self._image_list[self._index]
        record = self._file_dao.get_file_by_path(path)
        if record is None:
            return
        self.tag_editor.load_for_file(record.id)
        self.tag_editor.clear_new_input()
        self._toggle_drawer(True)

    def _apply_tags(self) -> None:
        """应用当前抽拉面板中的标签修改。"""
        if not self._tags_enabled:
            return
        path = self._image_list[self._index]
        record = self._file_dao.get_file_by_path(path)
        if record is None:
            return
        self._file_service.manage_file_tags(
            path, self.tag_editor.get_tags_to_add(), self.tag_editor.get_tags_to_remove())
        self._refresh_tags()
        self.tags_changed.emit()

    # ---- 右键菜单（作用于当前图片，与文件列表右键菜单一致）----
    def _show_context_menu(self, global_pos) -> None:
        """在图片上右键时弹出文件操作菜单。依赖齐备（_tags_enabled）时才可用。"""
        path = self._image_list[self._index]
        record = self._file_dao.get_file_by_path(path)
        file_exists = os.path.exists(path)

        menu = QMenu(self)
        act_top = menu.addAction("置顶")
        act_top.setCheckable(True)
        act_top.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        menu.addSeparator()
        act_open_dir = menu.addAction("打开文件目录")
        menu.addSeparator()
        act_rename = menu.addAction("重命名...")
        act_move = menu.addAction("移动到...")
        act_copy = menu.addAction("复制到...")
        act_clear_copy = menu.addAction("清空目标文件夹并复制...")
        menu.addSeparator()

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

        # 文件已缺失时禁用物理操作；未入库时禁用依赖数据库记录的项
        for act in (act_rename, act_move, act_copy, act_clear_copy, act_delete_phys):
            act.setEnabled(file_exists)
        act_copy_md5.setEnabled(record is not None and bool(record.md5))
        act_tag.setEnabled(record is not None)
        act_delete_db.setEnabled(record is not None)

        action = menu.exec(global_pos)
        if action is None:
            return
        if action == act_top:
            self._toggle_always_on_top(act_top.isChecked())
        elif action == act_open_dir:
            self._open_file_dir(path)
        elif action == act_rename:
            self._ctx_rename(record)
        elif action == act_move:
            self._ctx_transfer(is_move=True)
        elif action == act_copy:
            self._ctx_transfer(is_move=False)
        elif action == act_clear_copy:
            self._ctx_clear_and_copy()
        elif action == act_copy_path:
            self._copy_to_clipboard(path)
        elif action == act_copy_dir:
            self._copy_to_clipboard(os.path.dirname(path))
        elif action == act_copy_name:
            self._copy_to_clipboard(os.path.basename(path))
        elif action == act_copy_md5:
            self._copy_to_clipboard(record.md5 if record else "")
        elif action == act_tag:
            self._ctx_manage_tags(record)
        elif action == act_delete_phys:
            self._ctx_delete(physical=True)
        elif action == act_delete_db:
            self._ctx_delete(physical=False)

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _open_file_dir(self, path: str) -> None:
        from src.utils.file_utils import open_in_explorer
        open_in_explorer(path)

    def _ctx_rename(self, record) -> None:
        """重命名当前图片；成功后更新列表内路径并重新加载。"""
        from src.ui.dialogs.rename_dialog import RenameDialog
        from src.core.models import FileRecord

        old_path = self._image_list[self._index]
        if record is None:
            # 文件未入库也允许物理重命名（DB 同步失败时 service 会记录日志）
            record = FileRecord(id=0, path=old_path, name=os.path.basename(old_path),
                                size=0, modified_time=0.0, md5="", added_time=0.0)
        dialog = RenameDialog([record], self)
        if not dialog.exec():
            return
        new_name = dialog.get_rename_map().get(old_path)
        if not new_name or new_name == os.path.basename(old_path):
            return
        res = self._file_service.rename_file(old_path, new_name)
        if res.success_count > 0:
            self._image_list[self._index] = os.path.join(os.path.dirname(old_path), new_name)
            self._load_current()
            self.data_changed.emit()
        else:
            QMessageBox.warning(self, "重命名失败", "\n".join(res.errors) or res.message)

    def _toggle_always_on_top(self, enable: bool) -> None:
        """切换窗口置顶（仅由用户主动开启，默认不置顶）。"""
        flags = self.windowFlags()
        if enable:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # 修改窗口标志会重建原生窗口并隐藏，需要重新显示
        self.show()
        self._fit_and_center()

    def _ctx_transfer(self, is_move: bool) -> None:
        """移动/复制当前图片到目标文件夹（冲突自动重命名）。

        移动后原路径失效，从浏览列表移除并切换到下一张；复制不影响当前浏览。
        """
        path = self._image_list[self._index]
        title = "选择目标文件夹" if is_move else "选择复制目标文件夹"
        target_dir = QFileDialog.getExistingDirectory(self, title)
        if not target_dir:
            return
        if is_move:
            res = self._file_service.move_files([path], target_dir, conflict_strategy=STRATEGY_RENAME)
        else:
            res = self._file_service.copy_files([path], target_dir, conflict_strategy=STRATEGY_RENAME)
        if res.success_count <= 0:
            QMessageBox.warning(self, "操作失败", "\n".join(res.errors) or res.message)
            return
        self.data_changed.emit()
        if is_move:
            self._remove_current_from_list()

    def _ctx_clear_and_copy(self) -> None:
        """清空指定文件夹的全部内容，再把当前图片复制进去。

        目标文件夹若与当前图片所在文件夹相同会一并删掉源文件，因此禁止选择。
        """
        from src.ui.dialogs.confirm_dialog import ConfirmDialog

        path = self._image_list[self._index]
        target_dir = QFileDialog.getExistingDirectory(self, "选择要清空并复制的目标文件夹")
        if not target_dir:
            return

        same_dir = os.path.normcase(os.path.abspath(target_dir)) == \
            os.path.normcase(os.path.abspath(os.path.dirname(path)))
        if same_dir:
            QMessageBox.warning(self, "无法操作", "目标文件夹与当前图片所在文件夹相同，清空会删除源文件，请选择其他文件夹。")
            return

        if not self._skip_clear_confirm:
            ok, remember = ConfirmDialog.show_confirm_with_remember(
                "确认清空文件夹",
                f"将删除该文件夹中的全部内容：\n\n{target_dir}\n\n清空后再把当前图片复制进去，确定继续吗？",
                "记住选择（本次打开预览期间不再确认）",
                self)
            if not ok:
                return
            if remember:
                self._skip_clear_confirm = True

        # 清空目标文件夹内容（保留文件夹本身，符号链接/junction 只删链接）
        try:
            _clear_dir_contents(target_dir)
        except Exception as e:
            QMessageBox.warning(self, "清空失败", f"清空目标文件夹时出错：\n{e}")
            return

        res = self._file_service.copy_files([path], target_dir, conflict_strategy=STRATEGY_RENAME)
        if res.success_count <= 0:
            QMessageBox.warning(self, "复制失败", "\n".join(res.errors) or res.message)
            return
        self.data_changed.emit()

    def _ctx_manage_tags(self, record) -> None:
        """通过标签管理弹窗编辑当前图片的标签（复用全局标签管理逻辑）。"""
        if record is None:
            return
        from src.utils.tag_helper import manage_tags_for_files
        manage_tags_for_files(self, [record], self._tag_dao, self._file_service)
        self._refresh_tags()
        self.tags_changed.emit()

    def _ctx_delete(self, physical: bool) -> None:
        """删除当前图片：物理删除（回收站）或仅删数据库记录。"""
        from src.ui.dialogs.confirm_dialog import ConfirmDialog

        path = self._image_list[self._index]
        if physical:
            if not ConfirmDialog.show_confirm("确认删除", "确定要将当前图片移入回收站吗？", self):
                return
            res = self._file_service.delete_files([path], use_trash=True)
            if res.success_count <= 0:
                QMessageBox.warning(self, "删除失败", "\n".join(res.errors) or res.message)
                return
            self.data_changed.emit()
            self._remove_current_from_list()
        else:
            if not ConfirmDialog.show_confirm(
                    "确认逻辑删除", "确定要仅从数据库中删除当前图片的记录吗？\n物理文件将被保留。", self):
                return
            self._file_dao.delete_file_by_path(path)
            self.data_changed.emit()
            # 文件仍在磁盘上，继续显示；标签栏刷新为“未入库”状态
            self._refresh_tags()

    def _remove_current_from_list(self) -> None:
        """当前图片路径失效后从浏览列表移除，切到下一张；列表空则关闭查看器。"""
        del self._image_list[self._index]
        if not self._image_list:
            self.close()
            return
        if self._index >= len(self._image_list):
            self._index = len(self._image_list) - 1
        self._update_nav_buttons_visibility()
        self._load_current()

    # ---- 切换 ----
    def _update_nav_buttons_visibility(self):
        has_nav = len(self._image_list) > 1 or self._on_boundary is not None
        if has_nav:
            self.btn_prev.show()
            self.btn_next.show()
        else:
            self.btn_prev.hide()
            self.btn_next.hide()

    def _update_nav(self):
        total = len(self._image_list)
        at_first = self._index == 0
        at_last = self._index == total - 1

        # 若已到边界且提供了翻页回调，按钮仍保持启用，尝试翻页
        has_boundary_callback = self._on_boundary is not None
        self.btn_prev.setEnabled(not (at_first and not has_boundary_callback))
        self.btn_next.setEnabled(not (at_last and not has_boundary_callback))

    def _try_cross_page(self, direction: str) -> bool:
        """
        尝试跨页翻页。返回 True 表示成功加载新页并更新了索引。
        """
        if self._on_boundary is None:
            return False
        result = self._on_boundary(direction)
        if result is None:
            return False
        new_list, new_index = result
        if not new_list:
            return False
        self._image_list = new_list
        self._index = max(0, min(new_index, len(new_list) - 1))
        return True

    def show_prev(self):
        if self._index > 0:
            self._index -= 1
            self._load_current()
        elif self._try_cross_page("prev"):
            self._load_current()

    def show_next(self):
        if self._index < len(self._image_list) - 1:
            self._index += 1
            self._load_current()
        elif self._try_cross_page("next"):
            self._load_current()

    # ---- 交互 ----
    def eventFilter(self, obj, event):
        # 拦截 view 视口的滚轮事件：只缩放，不触发 QGraphicsView 默认滚动
        if obj == self.view.viewport() and event.type() == QEvent.Wheel:
            if self.item is not None:
                factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
                self.view.scale(factor, factor)
            return True  # 完全消费事件，阻止默认滚动
        # 双击恢复自适应（左键或中键均可）
        if obj == self.view.viewport() and event.type() == QEvent.MouseButtonDblClick:
            if event.button() in (Qt.LeftButton, Qt.MiddleButton) and self.item is not None:
                self._fit_and_center()
                return True
        # 右键弹出文件操作菜单（与文件列表右键菜单一致，作用于当前图片）
        if obj == self.view.viewport() and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.RightButton and self._tags_enabled:
                self._show_context_menu(event.globalPosition().toPoint())
                return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event: QWheelEvent):
        # 兜底：鼠标在视口外（如标题栏）时仍允许缩放
        if self.item is None:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event):
        # 左右方向键快速切换；T 打开标签编辑
        if event.key() == Qt.Key_Left:
            self.show_prev()
        elif event.key() == Qt.Key_Right:
            self.show_next()
        elif event.key() == Qt.Key_T and self._tags_enabled:
            self._edit_tags()
        else:
            super().keyPressEvent(event)
