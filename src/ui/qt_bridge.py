# === 文件路径: src/ui/qt_bridge.py ===
"""Qt 信号桥：core 事件总线 → Qt Signal。

- core 层（scanner / file_service / thumbnail_engine）只发纯 Python 事件
- 本模块在 UI 主线程首次调用 get_bridge() 时创建并完成订阅
- 工作线程 emit Qt Signal 属于跨线程信号（自动队列投递），线程安全
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.core.signals import (
    EVENT_DATA_CHANGED,
    EVENT_FILE_OPERATION,
    EVENT_THUMBNAIL_UPDATED,
    get_bus,
)


class QtBridge(QObject):
    scan_progress = Signal(int, int, str)          # (current, total, path)
    scan_finished = Signal(int, int)               # (added, updated)
    meta_progress = Signal(int, int, str)          # (current, total, path)
    meta_finished = Signal(int, int)               # (succeeded, failed)
    file_operation_result = Signal(str, bool, str) # (op_type, success, message)
    data_changed = Signal()
    thumbnail_updated = Signal(str, str)           # (file_path, thumb_path)
    file_selected = Signal(object)                 # FileRecord | None（UI 内部选中同步）


_bridge: QtBridge | None = None


def get_bridge() -> QtBridge:
    global _bridge
    if _bridge is None:
        bridge = QtBridge()
        bus = get_bus()

        bus.subscribe(EVENT_FILE_OPERATION,
                      lambda op, ok, msg: bridge.file_operation_result.emit(op, ok, msg))
        bus.subscribe(EVENT_DATA_CHANGED,
                      lambda: bridge.data_changed.emit())
        bus.subscribe(EVENT_THUMBNAIL_UPDATED,
                      lambda path, thumb: bridge.thumbnail_updated.emit(path, thumb))

        _bridge = bridge
    return _bridge


def clear_selection_signal() -> None:
    """便捷方法：发出空选中（清空详情面板）。"""
    get_bridge().file_selected.emit(None)
