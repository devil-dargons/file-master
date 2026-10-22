# === 文件路径: src/core/classifier.py ===
"""类型分类常量：扩展名 → 大类。扫描与分类共用，避免各处维护重复清单。"""
from __future__ import annotations

from pathlib import Path

# 大类 -> 扩展名集合（小写，含点）
EXT_TYPE_MAP: dict[str, set[str]] = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".svg", ".heic", ".heif", ".tif", ".tiff", ".psd"},
    "video": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus"},
    "document": {".txt", ".doc", ".docx", ".pdf", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".rtf", ".epub"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".h", ".json", ".xml", ".sql", ".go", ".rs"},
}

_EXT_LOOKUP: dict[str, str] = {
    ext: ftype for ftype, exts in EXT_TYPE_MAP.items() for ext in exts
}


def classify_ext(ext: str) -> str:
    """扩展名（如 '.jpg' / 'jpg'）→ 大类；未知返回 'other'。"""
    ext = ext.lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return _EXT_LOOKUP.get(ext, "other")


def classify_path(path: str) -> str:
    return classify_ext(Path(path).suffix)


# 扫描白名单（全部受支持扩展名的并集）
SUPPORTED_EXTS: frozenset[str] = frozenset(_EXT_LOOKUP.keys())
