# === 文件路径: src/config.py ===
import sys
import os
from pathlib import Path

APP_NAME = "FileMaster"
APP_VERSION = "1.0.0"

# 获取当前脚本所在的基础目录（兼容打包后的 exe）
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe，BASE_DIR 是 exe 所在的文件夹
    BASE_DIR = Path(sys.executable).parent
else:
    # 如果是源码运行，BASE_DIR 是项目根目录
    BASE_DIR = Path(__file__).resolve().parent.parent

# 【核心修改】将数据存储位置改到用户的 AppData 目录下
# 这样即使 exe 被移动或删除，数据依然安全保留在系统中
APPDATA_DIR = Path(os.environ.get('APPDATA')) / APP_NAME
os.makedirs(APPDATA_DIR, exist_ok=True)

DB_PATH = APPDATA_DIR / "filemaster.db"

# 缩略图也存到这里，防止被清理软件误删
THUMBNAIL_DIR = APPDATA_DIR / "thumbnails"
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
THUMBNAIL_MAX_WIDTH = 300 

LOG_DIR = APPDATA_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = LOG_DIR / "filemaster.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

MD5_CHUNK_SIZE = 8192
DB_BATCH_SIZE = 500
PAGE_SIZE = 50

FILE_TYPE_PRESETS = [
    "全部",
    "图片 (*.jpg;*.png;*.gif;*.bmp;*.webp)",
    "视频 (*.mp4;*.avi;*.mkv;*.mov;*.wmv)",
    "文档 (*.doc;*.docx;*.pdf;*.txt;*.md)",
    "代码 (*.py;*.js;*.html;*.css;*.java;*.cpp)",
    "压缩包 (*.zip;*.rar;*.7z;*.tar;*.gz)"
]