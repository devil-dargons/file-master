# === 文件路径: src/ui/widgets/image_delegate.py ===
from __future__ import annotations
import os
from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt

class ImageDelegate(QStyledItemDelegate):
    """
    用于在表格“预览”列中绘制图片的代理
    """
    def paint(self, painter: QPainter, option, index):
        # 获取单元格绑定的数据
        data = index.data(Qt.UserRole)
        
        image_path = None
        file_path = ''
        file_name = ''
        
        if isinstance(data, dict):
            image_path = data.get('thumbnail_path')
            file_path = data.get('path', '')
            file_name = data.get('name', '')
        elif isinstance(data, str):
            image_path = data
            file_path = data
            
        # 【核心优化】如果没有缩略图，且是图片格式，则直接使用原图路径
        if not image_path and file_name:
            ext = file_name.split('.')[-1].lower() if '.' in file_name else ""
            image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico'}
            if ext in image_exts and os.path.exists(file_path):
                image_path = file_path
                
        # 只有当有有效路径且文件存在时才绘制图片
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                rect = option.rect
                margin = 2
                target_rect = rect.adjusted(margin, margin, -margin, -margin)
                
                scaled_pixmap = pixmap.scaled(
                    target_rect.size(), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                
                x = target_rect.x() + (target_rect.width() - scaled_pixmap.width()) // 2
                y = target_rect.y() + (target_rect.height() - scaled_pixmap.height()) // 2
                
                painter.drawPixmap(x, y, scaled_pixmap)
                return
        
        # 如果没有图片，调用父类默认绘制（显示文字，即文件名）
        super().paint(painter, option, index)