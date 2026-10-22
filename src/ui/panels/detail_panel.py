# === 文件路径: src/ui/panels/detail_panel.py ===
from __future__ import annotations
import os
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QEvent
from src.utils.file_utils import format_file_size, format_timestamp, get_file_category
from src.core.models import FileRecord
from src.ui.widgets.image_viewer import ImageViewer


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

class DetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(200)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. 图片/视频预览区
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("无预览内容")
        self.preview_label.setProperty("role", "card")
        self.preview_label.setMinimumHeight(200)
        
        self.scroll_area = QScrollArea()
        # 允许内部 Label 随图片尺寸自动变化，确保滚动条范围 100% 准确
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.preview_label)
        self.scroll_area.setMinimumHeight(300)
        self.scroll_area.setAlignment(Qt.AlignCenter)

        # 隐藏滚动条：滚轮缩放已接管，无需滚动条 UI
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        main_layout.addWidget(self.scroll_area, 10)

        # 安装事件过滤器：统一接管滚轮缩放、拖拽平移、双击恢复自适应
        self.scroll_area.viewport().installEventFilter(self)
        # 预览图双击打开大图查看器
        self.preview_label.installEventFilter(self)
        
        # 2. 视频操作按钮
        self.btn_open_video = QPushButton("🎬 使用系统播放器打开")
        self.btn_open_video.hide()
        self.btn_open_video.clicked.connect(self._open_current_video)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_open_video)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        # 3. 详细信息区
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.NoFrame)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(15, 10, 15, 10)
        
        self.info_items = {
            "文件名": QLabel(), "路径": QLabel(), "大小": QLabel(), "宽高": QLabel(), "类型": QLabel(),
            "状态": QLabel(), "元数据": QLabel(), "MD5": QLabel(), "标签": QLabel(),
            "修改时间": QLabel()
        }
        
        for title, lbl in self.info_items.items():
            row_layout = QHBoxLayout()
            title_lbl = QLabel(f"{title}:")
            title_lbl.setProperty("role", "mutedBold")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(title_lbl)
            row_layout.addWidget(lbl, 1)
            info_layout.addLayout(row_layout)
            
        main_layout.addWidget(info_frame)

        self.original_pixmap = None
        self.current_scale_factor = 1.0
        self.current_image_path = None
        self.current_video_path = None
        self._is_panning = False
        self._pan_start_pos = None
        self._scroll_start_pos = None
        self._open_image_viewer_cb: "callable[[str], None] | None" = None

    def set_image_viewer_opener(self, callback: "callable[[str], None]") -> None:
        """绑定外部图片查看器打开回调（由主窗口连接 file_list_panel 提供）。"""
        self._open_image_viewer_cb = callback

    def eventFilter(self, obj, event):
        """统一拦截滚动区域内的滚轮和鼠标事件"""
        # 预览图双击（区分左键/中键）
        if obj == self.preview_label and event.type() == QEvent.MouseButtonDblClick:
            if not (self.current_image_path and os.path.exists(self.current_image_path)):
                return False
            if event.button() == Qt.MiddleButton:
                # 中键双击：恢复最适合大小
                if self.original_pixmap:
                    self._fit_preview_to_viewport()
                return True
            if event.button() == Qt.LeftButton:
                # 左键双击：打开大图查看器（复用 file_list_panel 的全局翻页逻辑）
                if self._open_image_viewer_cb:
                    self._open_image_viewer_cb(self.current_image_path)
                else:
                    ImageViewer(self.current_image_path, self).exec()
                return True
        if obj == self.scroll_area.viewport():
            # 1. 拦截滚轮：仅用于缩放，绝不触发滚动
            if event.type() == QEvent.Wheel and self.current_image_path:
                if event.angleDelta().y() > 0:
                    self.current_scale_factor *= 1.1
                else:
                    self.current_scale_factor /= 1.1
                if self.current_scale_factor < 0.1: self.current_scale_factor = 0.1

                self._update_preview_display()
                return True # 拦截事件，阻止滚动条响应

            # 2. 拦截鼠标按下：开始拖拽平移
            elif event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and self.current_image_path:
                if self.original_pixmap and self.current_scale_factor > 1.0: # 仅在放大时允许拖拽
                    self._is_panning = True
                    self._pan_start_pos = event.pos()
                    self._scroll_start_pos = (self.scroll_area.horizontalScrollBar().value(),
                                              self.scroll_area.verticalScrollBar().value())
                    self.setCursor(Qt.ClosedHandCursor)
                    return True

            # 3. 拦截鼠标移动：实时更新滚动条位置
            elif event.type() == QEvent.MouseMove and self._is_panning:
                delta = event.pos() - self._pan_start_pos
                self.scroll_area.horizontalScrollBar().setValue(self._scroll_start_pos[0] - delta.x())
                self.scroll_area.verticalScrollBar().setValue(self._scroll_start_pos[1] - delta.y())
                return True

            # 4. 拦截鼠标释放：结束拖拽
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self._is_panning:
                    self._is_panning = False
                    self.setCursor(Qt.ArrowCursor)
                    return True

            # 5. 双击恢复最适合大小查看（左键或中键均可）
            elif event.type() == QEvent.MouseButtonDblClick and event.button() in (Qt.LeftButton, Qt.MiddleButton):
                if self.current_image_path and self.original_pixmap:
                    self._fit_preview_to_viewport()
                    return True

        return super().eventFilter(obj, event)

    def _fit_preview_to_viewport(self):
        """详情面板预览图恢复最适合大小：宽度自适应视口，保持宽高比。"""
        if self.original_pixmap is None or self.original_pixmap.width() == 0:
            return
        viewport_width = self.scroll_area.viewport().width()
        if viewport_width <= 10:
            viewport_width = 320
        self.current_scale_factor = viewport_width / self.original_pixmap.width()
        self._update_preview_display()
        # 重置滚动位置到顶部
        self.scroll_area.horizontalScrollBar().setValue(0)
        self.scroll_area.verticalScrollBar().setValue(0)

    @staticmethod
    def _format_meta(meta) -> str:
        """把 MediaMeta 拼成一行摘要：分辨率 · 时长 · 页数 · 拍摄时间 · 相机。"""
        if meta is None:
            return "-"
        parts = []
        if meta.width and meta.height:
            parts.append(f"{meta.width}×{meta.height}")
        if meta.duration_sec:
            parts.append(_format_duration(meta.duration_sec))
        if meta.page_count:
            parts.append(f"{meta.page_count} 页")
        if meta.shot_time:
            parts.append(meta.shot_time)
        if meta.camera:
            parts.append(meta.camera)
        return " · ".join(parts) or "-"

    def _set_elided_text(self, label: QLabel, text: str):
        label.setText(text)
        label.setToolTip(text)
        if len(text) > 40: label.setText(text[:37] + "...")

    def update_detail(self, file_data: FileRecord | None):
        if not file_data:
            self._clear()
            return

        path = file_data.path
        name = file_data.name
        ext = name.split('.')[-1].lower() if '.' in name else ""

        self._set_elided_text(self.info_items["文件名"], name)
        self._set_elided_text(self.info_items["路径"], path)
        self.info_items["大小"].setText(format_file_size(file_data.size))
        # 宽高：独立字段（元数据摘要里也含分辨率，但这里单独展示更直观）
        meta = file_data.meta
        if meta and meta.width and meta.height:
            self.info_items["宽高"].setText(f"{meta.width} × {meta.height}")
        else:
            self.info_items["宽高"].setText("-")
        self.info_items["类型"].setText(get_file_category(path))
        self.info_items["状态"].setText("已失联（原路径不存在）" if file_data.missing else "正常")
        self._set_elided_text(self.info_items["元数据"], self._format_meta(file_data.meta))
        self._set_elided_text(self.info_items["MD5"], file_data.md5)
        self._set_elided_text(self.info_items["标签"], file_data.tags_str or "无")
        self.info_items["修改时间"].setText(format_timestamp(file_data.modified_time))
        
        # 重置状态
        self.btn_open_video.hide()
        self.preview_label.clear()
        self.current_image_path = None
        self.current_video_path = None
        self.original_pixmap = None
        self.current_scale_factor = 1.0
        
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
        video_exts = {'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'}
        
        if ext in image_exts:
            self.current_image_path = path
            self.original_pixmap = QPixmap(path)

            if not self.original_pixmap.isNull():
                # 【核心优化 3】精确计算初始宽度：使用视口实际宽度（已自动扣除滚动条）
                viewport_width = self.scroll_area.viewport().width()
                if viewport_width <= 10: viewport_width = 320 # 窗口未渲染完时的保底值

                if self.original_pixmap.width() > 0:
                    self.current_scale_factor = viewport_width / self.original_pixmap.width()
                else:
                    self.current_scale_factor = 1.0

                self._update_preview_display()
                self.preview_label.setToolTip("双击查看原图 | 中键双击恢复大小 | 滚轮缩放 | 放大后左键拖拽")
            else:
                # 文件存在但无法解码（被独占锁定 / 权限拒绝 / 文件损坏）
                self.current_image_path = None
                self.preview_label.setText("🔒 图片加载失败\n文件可能被其他程序锁定，或无读取权限")
                self.preview_label.setToolTip(path)
                
        elif ext in video_exts:
            thumb_path = file_data.thumbnail_path
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path)
                self.preview_label.setPixmap(pixmap.scaled(
                    self.scroll_area.viewport().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
            else:
                self.preview_label.setText("视频预览加载中...")
            self.btn_open_video.show()
            self.current_video_path = path
        else:
            self.preview_label.setText("该文件类型不支持预览")

    def _update_preview_display(self):
        if self.original_pixmap is None: return
            
        original_size = self.original_pixmap.size()
        target_width = int(original_size.width() * self.current_scale_factor)
        target_height = int(original_size.height() * self.current_scale_factor)
        
        if target_width < 50: target_width = 50
        if target_height < 50: target_height = 50

        scaled_pixmap = self.original_pixmap.scaled(
            target_width, target_height,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        
        self.preview_label.setPixmap(scaled_pixmap)

    def _open_current_video(self):
        if hasattr(self, 'current_video_path') and self.current_video_path:
            if os.name == 'nt': os.startfile(self.current_video_path)
            elif os.name == 'posix': subprocess.call(('open', self.current_video_path))

    def _clear(self):
        self.preview_label.clear()
        self.preview_label.setText("请选择文件查看详情")
        self.btn_open_video.hide()
        self.current_image_path = None
        self.current_video_path = None
        self.original_pixmap = None
        self.current_scale_factor = 1.0
        for lbl in self.info_items.values(): lbl.clear()