# === 文件路径: src/ui/panels/detail_panel.py ===
from __future__ import annotations
import os
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame
)
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtCore import Qt
from src.utils.file_utils import format_file_size, format_timestamp, get_file_category

class DetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(450)
        self.setStyleSheet("background-color: #ffffff; border-left: 1px solid #e0e0e0;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. 图片/视频预览区
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(400)
        self.preview_label.setStyleSheet("border-bottom: 1px solid #eee; background-color: #fafafa;")
        self.preview_label.setText("无预览内容")
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.preview_label)
        self.scroll_area.setStyleSheet("border: none;")
        main_layout.addWidget(self.scroll_area, 10)
        
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
            "文件名": QLabel(),
            "路径": QLabel(),
            "大小": QLabel(),
            "类型": QLabel(),
            "MD5": QLabel(),
            "标签": QLabel(),
            "修改时间": QLabel()
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

        # 【核心修复】用于存储原始高清图片的变量
        self.original_pixmap = None
        self.current_scale_factor = 1.0 # 记录当前的缩放倍数

    def _set_elided_text(self, label: QLabel, text: str):
        label.setText(text)
        label.setToolTip(text)
        if len(text) > 40:
            label.setText(text[:37] + "...")

    def update_detail(self, file_data: dict):
        if not file_data:
            self._clear()
            return
            
        path = file_data['path']
        name = file_data['name']
        ext = name.split('.')[-1].lower() if '.' in name else ""
        
        # 更新文字信息
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
            # 【核心修复】加载原图并保存到内存变量
            self.original_pixmap = QPixmap(path)
            
            if not self.original_pixmap.isNull():
                # 初始显示时，缩放到适合窗口的大小
                self._update_preview_display()
                self.preview_label.setToolTip("双击查看原图 | 滚轮缩放")
        elif ext in video_exts:
            thumb_path = file_data.get('thumbnail_path')
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path)
                self.preview_label.setPixmap(pixmap.scaled(
                    self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
            else:
                self.preview_label.setText("视频预览加载中...")
            self.btn_open_video.show()
            self.current_video_path = path
        else:
            self.preview_label.setText("该文件类型不支持预览")

    def _update_preview_display(self):
        """根据当前的缩放倍数，从原图生成显示图"""
        if self.original_pixmap is None:
            return
            
        # 获取原图尺寸
        original_size = self.original_pixmap.size()
        
        # 计算目标尺寸：原图尺寸 * 缩放倍数
        target_width = int(original_size.width() * self.current_scale_factor)
        target_height = int(original_size.height() * self.current_scale_factor)
        
        # 如果目标尺寸太小，至少保持 50px 防止消失
        if target_width < 50: target_width = 50
        if target_height < 50: target_height = 50

        # 【核心修复】始终从 self.original_pixmap 进行缩放，保证画质
        scaled_pixmap = self.original_pixmap.scaled(
            target_width, target_height,
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation # 高质量平滑缩放
        )
        
        self.preview_label.setPixmap(scaled_pixmap)

    def wheelEvent(self, event: QWheelEvent):
        # 滚轮缩放逻辑
        if self.current_image_path and self.scroll_area.underMouse():
            # 调整缩放倍数
            if event.angleDelta().y() > 0:
                self.current_scale_factor *= 1.1
            else:
                self.current_scale_factor /= 1.1
                
            # 限制最小缩放倍数，防止图片过小
            if self.current_scale_factor < 0.1:
                self.current_scale_factor = 0.1
                
            # 重新渲染
            self._update_preview_display()
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.current_image_path and os.path.exists(self.current_image_path):
            if os.name == 'nt':
                os.startfile(self.current_image_path)
            elif os.name == 'posix':
                subprocess.call(('open', self.current_image_path))
        super().mouseDoubleClickEvent(event)

    def _open_current_video(self):
        if hasattr(self, 'current_video_path') and self.current_video_path:
            if os.name == 'nt':
                os.startfile(self.current_video_path)
            elif os.name == 'posix':
                subprocess.call(('open', self.current_video_path))

    def _clear(self):
        self.preview_label.clear()
        self.preview_label.setText("请选择文件查看详情")
        self.btn_open_video.hide()
        self.current_image_path = None
        self.current_video_path = None
        self.original_pixmap = None
        self.current_scale_factor = 1.0
        for lbl in self.info_items.values():
            lbl.clear()