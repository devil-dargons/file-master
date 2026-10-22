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
from src.config import LOG_FILE, LOG_LEVEL, LOG_FORMAT, APP_NAME, VAULT_DIR
from src.core.vault import VaultService
from src.db.dao import SettingsDAO, VaultDAO
from src.db.database import DatabaseManager
from src.ui import themes
from src.ui.main_window import MainWindow

def setup_logging():
    """配置全局日志系统，将日志同时输出到文件和控制台"""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
    if sys.stdout is not None:  # 打包为无控制台 exe 时 stdout 为 None，仅写文件
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=LOG_FORMAT,
        handlers=handlers,
    )
    logging.info("="*30 + " FileMaster Application Starting " + "="*30)

def main():
    # 1. 初始化日志
    setup_logging()
    
    # 2. 高 DPI 缩放适配
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    # 3. 创建 Qt 应用程序实例
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    
    # 4. 跨平台中文字体适配
    font = QFont()
    if sys.platform == 'win32':
        font = QFont("Microsoft YaHei UI", 9)
    elif sys.platform == 'darwin':
        font = QFont("PingFang SC", 12)
    elif sys.platform.startswith('linux'):
        font = QFont("WenQuanYi Micro Hei", 10)
    app.setFont(font)
    
    # 5. 应用主题（暗色为默认；按持久化设置覆盖，启动锁对话框也随主题显示）
    db_manager = DatabaseManager()
    settings_dao = SettingsDAO(db_manager)
    saved_theme = settings_dao.get_setting("theme", themes.palette.DEFAULT_THEME)
    themes.apply_theme(app, saved_theme if saved_theme in themes.palette.THEMES
                       else themes.palette.DEFAULT_THEME)

    # 6. 启动锁（M4 安全）：未设主密码 → 设置向导；已设 → 验证；取消则退出
    from src.ui.dialogs.lock_dialog import LockDialog
    vault_service = VaultService(db_manager, settings_dao, VaultDAO(db_manager), VAULT_DIR)
    if not LockDialog.run(vault_service):
        logging.info("Startup lock cancelled by user, exiting.")
        sys.exit(0)

    # 7. 实例化并显示主窗口
    window = MainWindow()
    window.show()

    logging.info("Main window initialized and shown.")

    # 8. 进入主事件循环
    sys.exit(app.exec())

if __name__ == "__main__":
    main()