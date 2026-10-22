# === 文件路径: src/core/thumbnail_engine.py ===
"""异步缩略图引擎：纯 threading 实现，不感知 Qt。

完成后更新数据库并通过事件总线广播 EVENT_THUMBNAIL_UPDATED，
UI 层经 qt_bridge 局部刷新对应行。
"""
from __future__ import annotations

import logging
import threading
import time

from src.core.signals import EVENT_THUMBNAIL_UPDATED, get_bus
from src.db.dao import FileDAO
from src.db.database import DatabaseManager
from src.utils.file_utils import get_video_first_frame

logger = logging.getLogger(__name__)


class ThumbnailManager(threading.Thread):
    """缩略图工作线程：维护任务队列，异步提取并更新数据库。"""

    def __init__(self):
        super().__init__(daemon=True, name="ThumbnailManager")
        self.task_queue: list[tuple[str, str]] = []
        self._queue_lock = threading.Lock()
        self._stop_event = threading.Event()
        self.bus = get_bus()

        self._dao = FileDAO(DatabaseManager())

    def run(self) -> None:
        while not self._stop_event.is_set():
            task = None
            with self._queue_lock:
                if self.task_queue:
                    task = self.task_queue.pop(0)
            if task:
                self._process(*task)
            else:
                time.sleep(0.2)

    def add_task(self, file_path: str, md5: str) -> None:
        with self._queue_lock:
            # 简单去重：队列里已有同路径任务则跳过
            if any(t[0] == file_path for t in self.task_queue):
                return
            self.task_queue.append((file_path, md5))

    def _process(self, file_path: str, md5: str) -> None:
        try:
            thumb_path = get_video_first_frame(file_path, md5)
        except Exception:
            logger.exception("Thumbnail generation failed: %s", file_path)
            return

        if thumb_path:
            self._dao.update_thumbnail_path(file_path, thumb_path)
            try:
                self.bus.emit(EVENT_THUMBNAIL_UPDATED, file_path, thumb_path)
            except Exception:
                logger.exception("thumbnail_updated emit failed")

    def stop(self) -> None:
        self._stop_event.set()
