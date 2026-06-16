# === 文件路径: src/core/signals.py ===
from __future__ import annotations  # 兼容低版本 Python
from PySide6.QtCore import QObject, Signal

class AppSignals(QObject):
    """
    全局自定义信号中心 (单例模式)
    """
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent=None):
        if AppSignals._initialized:
            return
            
        super().__init__(parent)
        AppSignals._initialized = True

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
    
    # ==========================================
    # 4. 【新增】局部刷新与全局详情同步信号
    # ==========================================
    # 用于后台生成完缩略图后，通知表格只刷新对应的那一行 (file_path, thumb_path)
    thumbnail_updated = Signal(str, str)
    
    # 用于任何面板选中文件时，通知主窗口更新右侧详情面板 (file_data_dict)
    file_selected = Signal(dict)