from __future__ import annotations  # 兼容低版本 Python
from PySide6.QtCore import QObject, Signal

class AppSignals(QObject):
    """
    全局自定义信号中心 (单例模式)
    """
    _instance = None
    _initialized = False  # <--- 新增：用于标记是否已经初始化过

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent=None):
        # <--- 核心修复：如果已经初始化过，直接返回，绝不调用 super().__init__()
        if AppSignals._initialized:
            return
            
        super().__init__(parent)
        AppSignals._initialized = True  # 标记为已初始化

    # ==========================================
    # 1. 扫描引擎相关信号
    # ==========================================
    scan_progress = Signal(int, int, str)
    scan_finished = Signal(int, int)

    # ==========================================
    # 2. 文件操作总线相关信号
    # ==========================================
    file_operation_result = Signal(str, bool, str)

    # ==========================================
    # 3. 全局状态刷新信号
    # ==========================================
    data_changed = Signal()