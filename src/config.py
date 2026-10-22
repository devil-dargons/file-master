# === 文件路径: src/config.py ===
"""路径解析链与常量（开发手册 5.1）。

数据目录按序判定：
1. 命令行参数 `--data-dir <path>`（调试用）
2. 环境变量 `FILEMASTER_DATA_DIR`
3. 便携标记：exe 同目录存在 `portable.flag` → `<exe目录>/data`
4. 指针文件：`%APPDATA%/FileMaster/data_location.txt`（内容一行绝对路径，永不迁移）
5. 默认：`%APPDATA%/FileMaster`
"""
from __future__ import annotations

import sys
import os
import logging
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "FileMaster"
APP_VERSION = "2.0.0"

POINTER_FILE_NAME = "data_location.txt"
PORTABLE_FLAG_NAME = "portable.flag"

# 获取当前脚本所在的基础目录（兼容打包后的 exe）
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent


def default_data_root() -> Path:
    """默认数据根：`%APPDATA%/FileMaster`（指针文件所在处，永不迁移）。"""
    appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    return Path(appdata) / APP_NAME


def resolve_data_dir(argv: list[str] | None = None, env: Mapping[str, str] | None = None,
                     base_dir: Path | None = None, default_root: Path | None = None) -> Path:
    """路径解析链（纯函数，可测试）。返回选定的数据目录。"""
    argv = list(sys.argv) if argv is None else list(argv)
    env_view: Mapping[str, str] = os.environ if env is None else env
    base_dir = base_dir if base_dir is not None else BASE_DIR
    default_root = default_root if default_root is not None else default_data_root()

    # 1. 命令行参数
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        if i + 1 < len(argv):
            return Path(argv[i + 1])

    # 2. 环境变量
    env_dir = env_view.get("FILEMASTER_DATA_DIR")
    if env_dir:
        return Path(env_dir)

    # 3. 便携标记
    if (base_dir / PORTABLE_FLAG_NAME).exists():
        return base_dir / "data"

    # 4. 指针文件
    pointer = default_root / POINTER_FILE_NAME
    if pointer.is_file():
        try:
            target = Path(pointer.read_text(encoding="utf-8").strip())
            if target.is_absolute():
                return target
            logger.warning("Pointer file has non-absolute path, ignored: %s", target)
        except (OSError, ValueError) as e:
            logger.warning("Cannot read pointer file %s: %s", pointer, e)

    # 5. 默认
    return default_root


def _ensure_dir(path: Path) -> None:
    """尽力创建数据目录；无权限时仅告警（由各写入点自行兜底）。"""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        logger.warning("Cannot create data dir %s: %s", path, e)


APPDATA_DIR = resolve_data_dir()          # 数据目录（可能是迁移后的自定义位置）
DEFAULT_DATA_ROOT = default_data_root()   # 指针文件固定所在处
_ensure_dir(APPDATA_DIR)

DB_PATH = APPDATA_DIR / "filemaster.db"

# 缩略图也存到这里，防止被清理软件误删
THUMBNAIL_DIR = APPDATA_DIR / "thumbnails"
_ensure_dir(THUMBNAIL_DIR)
THUMBNAIL_MAX_WIDTH = 300

# Vault 加密文件密文存储 / 加密备份导出（M4 安全模块）
VAULT_DIR = APPDATA_DIR / "vault"
BACKUP_DIR = APPDATA_DIR / "backups"
_ensure_dir(VAULT_DIR)
_ensure_dir(BACKUP_DIR)

LOG_DIR = APPDATA_DIR / "logs"
_ensure_dir(LOG_DIR)
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
    "音频 (*.mp3;*.wav;*.flac;*.aac;*.ogg;*.m4a)",
    "文档 (*.doc;*.docx;*.pdf;*.txt;*.md)",
    "代码 (*.py;*.js;*.html;*.css;*.java;*.cpp)",
    "压缩包 (*.zip;*.rar;*.7z;*.tar;*.gz)"
]
