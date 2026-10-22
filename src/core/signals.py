# === 文件路径: src/core/signals.py ===
"""进程内事件总线（纯 Python，可从任意线程 emit，无 Qt 依赖）。

core 层通过本模块上报进度/状态变化；UI 层在 ui/qt_bridge.py 中订阅并转为 Qt Signal。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# ---- 事件名常量 ----
EVENT_DATA_CHANGED = "data_changed"                      # 数据集发生变化，UI 应刷新
EVENT_FILE_OPERATION = "file_operation_result"           # (op_type, success, message)
EVENT_THUMBNAIL_UPDATED = "thumbnail_updated"            # (file_path, thumb_path)


class EventBus:
    """同步事件总线：emit 时在调用线程内依次执行订阅者。

    约定：跨线程订阅者（UI）必须自行保证线程安全——QtBridge 内部只做
    Qt Signal emit（跨线程信号为队列投递，天然安全）。
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Callable) -> None:
        with self._lock:
            self._subs.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        with self._lock:
            handlers = self._subs.get(event)
            if handlers and handler in handlers:
                handlers.remove(handler)

    def emit(self, event: str, *args) -> None:
        with self._lock:
            handlers = list(self._subs.get(event, ()))
        for handler in handlers:
            try:
                handler(*args)
            except Exception:
                logger.exception("EventBus handler failed for event %r", event)


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus
