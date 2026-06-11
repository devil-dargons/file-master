# === 文件路径: src/ui/widgets/image_viewer.py ===
from __future__ import annotations
from PySide6.QtWidgets import QDialog, QVBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from PySide6.QtGui import QPixmap, QWheelEvent, QPainter
from PySide6.QtCore import Qt

class ImageViewer(QDialog):
    """
    支持滚轮缩放的图片查看器
    """
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        
        layout = QVBoxLayout(self)
        self.view = QGraphicsView()
        self.scene = QGraphicsScene()
        self.view.setScene(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        
        # 加载图片
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self.item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(self.item)
            # 初始适应窗口
            self.view.fitInView(self.item, Qt.KeepAspectRatio)
        
        layout.addWidget(self.view)
        self.resize(800, 600)

    def wheelEvent(self, event: QWheelEvent):
        # 实现滚轮缩放
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)
        event.accept()