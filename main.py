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
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# 导入我们在 Phase 2 定义的配置
from src.config import LOG_FILE, LOG_LEVEL, LOG_FORMAT, APP_NAME, VAULT_DIR
from src.core.vault import VaultService
from src.db.dao import SettingsDAO, VaultDAO
from src.db.database import DatabaseManager
from src.ui import themes
from src.ui.main_window import MainWindow

# 单实例本地服务名（同一机器同一用户会话内唯一）
_SINGLE_INSTANCE_KEY = "FileMaster-SingleInstance"


def notify_running_instance() -> bool:
    """尝试连接已运行的实例并通知其把主窗口提到前台。

    连接成功说明已有实例在运行，返回 True（本进程应直接退出）。
    """
    sock = QLocalSocket()
    sock.connectToServer(_SINGLE_INSTANCE_KEY)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"raise")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True

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

    # 3.5 单实例：已有实例在运行 → 通知其显示主窗口，本进程直接退出
    if notify_running_instance():
        logging.info("Another instance is already running, activating it and exiting.")
        sys.exit(0)
    
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

    # 7.5 单实例服务端：后续实例启动时通过本地 socket 通知本进程，把主窗口提到前台
    server = QLocalServer(app)
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)  # 清理异常退出残留的监听名（Unix 域 socket）
    server.listen(_SINGLE_INSTANCE_KEY)

    def _on_second_instance():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readAll()
            conn.disconnectFromServer()
            conn.deleteLater()
        window.bring_to_front()

    server.newConnection.connect(_on_second_instance)

    logging.info("Main window initialized and shown.")

    # 8. 进入主事件循环
    sys.exit(app.exec())

if __name__ == "__main__":
    main()