# === 文件路径: src/ui/panels/detail_panel.py ===
from __future__ import annotations
import os
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame
)
from PySide6.QtGui import QPixmap, QWheelEvent, QMouseEvent
from PySide6.QtCore import Qt, QEvent
from src.utils.file_utils import format_file_size, format_timestamp, get_file_category

class DetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(200)
        self.setMaximumWidth(450)
        self.setStyleSheet("background-color: #ffffff; border-left: 1px solid #e0e0e0;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. 图片/视频预览区
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("无预览内容")
        self.preview_label.setStyleSheet("background-color: #fafafa;")
        
        self.scroll_area = QScrollArea()
        # 允许内部 Label 随图片尺寸自动变化，确保滚动条范围 100% 准确
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.preview_label)
        self.scroll_area.setMinimumHeight(300)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        
        # 【核心优化 1】美化滚动条：8px 细宽、圆角、半透明、隐藏上下箭头按钮
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 8px; background: transparent; margin: 0px; }
            QScrollBar::handle:vertical { background: rgba(150, 150, 150, 0.6); border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: rgba(100, 100, 100, 0.8); }
            QScrollBar:horizontal { height: 8px; background: transparent; margin: 0px; }
            QScrollBar::handle:horizontal { background: rgba(150, 150, 150, 0.6); border-radius: 4px; min-width: 30px; }
            QScrollBar::handle:horizontal:hover { background: rgba(100, 100, 100, 0.8); }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; background: none; }
            QScrollBar::add-page, QScrollBar::sub-page { background: none; }
        """)
        main_layout.addWidget(self.scroll_area, 10)
        
        # 【核心优化 2】安装事件过滤器：统一接管滚轮和鼠标拖动事件
        self.scroll_area.viewport().installEventFilter(self)
        
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
            "文件名": QLabel(), "路径": QLabel(), "大小": QLabel(),
            "类型": QLabel(), "MD5": QLabel(), "标签": QLabel(), "修改时间": QLabel()
        }
        
        for title, lbl in self.info_items.items():
            row_layout = QHBoxLayout()
            title_lbl = QLabel(f"{title}:")
            title_lbl.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
            lbl.setStyleSheet("color: #333;")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(title_lbl)
            row_layout.addWidget(lbl, 1)
            info_layout.addLayout(row_layout)
            
        main_layout.addWidget(info_frame)

        self.original_pixmap = None
        self.current_scale_factor = 1.0
        self._is_panning = False
        self._pan_start_pos = None
        self._scroll_start_pos = None

    def eventFilter(self, obj, event):
        """统一拦截滚动区域内的滚轮和鼠标事件"""
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
                    
        return super().eventFilter(obj, event)

    def _set_elided_text(self, label: QLabel, text: str):
        label.setText(text)
        label.setToolTip(text)
        if len(text) > 40: label.setText(text[:37] + "...")

    def update_detail(self, file_data: dict):
        if not file_data:
            self._clear()
            return
            
        path = file_data['path']
        name = file_data['name']
        ext = name.split('.')[-1].lower() if '.' in name else ""
        
        self._set_elided_text(self.info_items["文件名"], name)
        self._set_elided_text(self.info_items["路径"], path)
        self.info_items["大小"].setText(format_file_size(file_data['size']))
        self.info_items["类型"].setText(get_file_category(path))
        self._set_elided_text(self.info_items["MD5"], file_data['md5'])
        self._set_elided_text(self.info_items["标签"], file_data.get('tags_str', '无'))
        self.info_items["修改时间"].setText(format_timestamp(file_data['modified_time']))
        
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
                self.preview_label.setToolTip("双击查看原图 | 滚轮缩放 | 放大后左键拖拽")
                
        elif ext in video_exts:
            thumb_path = file_data.get('thumbnail_path')
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