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
        
        # 如果数据是字典，尝试从中提取 thumbnail_path
        image_path = None
        if isinstance(data, dict):
            image_path = data.get('thumbnail_path')
        elif isinstance(data, str):
            image_path = data
            
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