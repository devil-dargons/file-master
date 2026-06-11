from __future__ import annotations

import sys
import os
import logging

# 1. 路径修正：确保项目根目录在 sys.path 中，防止在部分 IDE 或打包后出现 import 找不到 src 的问题
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# 导入我们在 Phase 2 定义的配置
from src.config import LOG_FILE, LOG_LEVEL, LOG_FORMAT
from src.ui.main_window import MainWindow

def setup_logging():
    """配置全局日志系统，将日志同时输出到文件和控制台"""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout) 
        ]
    )
    logging.info("="*30 + " FileMaster Application Starting " + "="*30)

def main():
    # 1. 初始化日志
    setup_logging()
    
    # 2. 高 DPI 缩放适配
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    # 3. 创建 Qt 应用程序实例
    app = QApplication(sys.argv)
    
    # 4. 跨平台中文字体适配
    font = QFont()
    if sys.platform == 'win32':
        font = QFont("Microsoft YaHei", 10)
    elif sys.platform == 'darwin':
        font = QFont("PingFang SC", 12)
    elif sys.platform.startswith('linux'):
        font = QFont("WenQuanYi Micro Hei", 10)
    app.setFont(font)
    
    # 5. 全局 QSS 样式微调 (让界面更现代化)
    app.setStyleSheet("""
        QMainWindow { background-color: #fafafa; }
        QPushButton { 
            padding: 6px 12px; 
            border: 1px solid #d0d0d0; 
            border-radius: 4px; 
            background-color: #ffffff; 
            color: #333;
        }
        QPushButton:hover { background-color: #f0f0f0; border-color: #bbb; }
        QPushButton:pressed { background-color: #e0e0e0; }
        QPushButton:disabled { background-color: #f5f5f5; color: #999; }
        
        QTableWidget, QTreeWidget, QListWidget { 
            border: 1px solid #e0e0e0; 
            gridline-color: #f5f5f5; 
            selection-background-color: #e3f2fd; 
            selection-color: #000;
        }
        QHeaderView::section { 
            background-color: #f9f9f9; 
            padding: 5px; 
            border: 1px solid #e0e0e0; 
            font-weight: bold; 
            color: #555;
        }
        QProgressBar {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            text-align: center;
            background-color: #f0f0f0;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
            border-radius: 3px;
        }
    """)

    # 6. 实例化并显示主窗口
    window = MainWindow()
    window.show()
    
    logging.info("Main window initialized and shown.")
    
    # 7. 进入主事件循环
    sys.exit(app.exec())

if __name__ == "__main__":
    main()