# === 文件路径: src/core/thumbnail_engine.py ===
from __future__ import annotations
import os
from PySide6.QtCore import QThread, Signal, QObject
from src.utils.file_utils import get_video_first_frame
from src.core.signals import AppSignals
from src.db.database_manager import DatabaseManager
from src.db.dao import FileDAO

class ThumbnailWorker(QObject):
    """单个任务处理器"""
    finished = Signal(str, str, bool) # (file_path, thumb_path, success)

    def process(self, file_path: str, md5: str):
        thumb_path = get_video_first_frame(file_path, md5)
        self.finished.emit(file_path, thumb_path or "", thumb_path is not None)

class ThumbnailManager(QThread):
    """
    缩略图管理线程：维护队列，异步提取并更新数据库
    """
    def __init__(self):
        super().__init__()
        self.task_queue = []
        self.is_running = True
        self.signals = AppSignals()
        
        # 初始化工作对象
        self.worker = ThumbnailWorker()
        self.worker.moveToThread(self)
        self.worker.finished.connect(self._on_task_finished)

    def run(self):
        while self.is_running:
            if self.task_queue:
                file_path, md5 = self.task_queue.pop(0)
                self.worker.process(file_path, md5)
            else:
                self.msleep(200) # 队列为空时休眠

    def add_task(self, file_path: str, md5: str):
        # 简单的去重：如果队列里已经有了，就不重复添加
        if not any(t[0] == file_path for t in self.task_queue):
            self.task_queue.append((file_path, md5))

    def _on_task_finished(self, file_path: str, thumb_path: str, success: bool):
        if success and thumb_path:
            # 1. 更新数据库
            db = DatabaseManager()
            dao = FileDAO(db)
            dao.update_thumbnail_path(file_path, thumb_path)
            
            # 2. 【核心修改】发射局部更新信号，而不是全局 data_changed，防止表格频繁重载卡死
            self.signals.thumbnail_updated.emit(file_path, thumb_path)

    def stop(self):
        self.is_running = False