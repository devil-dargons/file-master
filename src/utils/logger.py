import logging
import sys
import os
from logging.handlers import RotatingFileHandler

from src.config import LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DIR

class ColorFormatter(logging.Formatter):
    """
    为控制台日志添加颜色，区分日志级别，提升可读性。
    """
    COLORS = {
        'DEBUG': '\033[37m',    # 白色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[41m', # 红底白字
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

def setup_advanced_logging():
    """
    配置高级全局日志系统。
    特性：
    1. 控制台输出带颜色。
    2. 文件输出支持按大小轮转（每个文件最大 5MB，保留 3 个备份），防止日志撑爆硬盘。
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    
    # 清空已有的 handlers，防止重复添加（特别是在 IDE 中多次运行）
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    color_formatter = ColorFormatter(LOG_FORMAT)

    # 1. 控制台 Handler (带颜色)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(color_formatter)
    root_logger.addHandler(console_handler)

    # 2. 文件 Handler (按大小轮转: 5MB/个，保留3个备份)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, 
            maxBytes=5 * 1024 * 1024, 
            backupCount=3, 
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        root_logger.error(f"Failed to initialize file logger: {e}")

    root_logger.info("Advanced logging system initialized with rotation.")