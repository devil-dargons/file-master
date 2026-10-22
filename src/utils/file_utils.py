# === 文件路径: src/utils/file_utils.py ===
from __future__ import annotations
import time
import os
import cv2
import numpy as np
from pathlib import Path
from src.config import THUMBNAIL_DIR, THUMBNAIL_MAX_WIDTH

# 常见文件分类字典
FILE_CATEGORIES = {
    "文档": {".txt", ".doc", ".docx", ".pdf", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".psd"},
    "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso"},
    "代码": {".py", ".js", ".html", ".css", ".java", ".c", ".cpp", ".h", ".json", ".xml", ".sql"}
}

def format_file_size(size_bytes: int | float) -> str:
    if size_bytes < 0:
        return "未知"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} EB"

def format_timestamp(timestamp: float, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not timestamp:
        return ""
    try:
        return time.strftime(fmt, time.localtime(timestamp))
    except (ValueError, TypeError, OSError):
        return "时间无效"

def get_file_category(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    for category, extensions in FILE_CATEGORIES.items():
        if ext in extensions:
            return category
    return "其他"

def get_unique_file_path(target_path: Path) -> Path:
    if not target_path.exists():
        return target_path
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1

def is_safe_path(base_dir: str, target_path: str) -> bool:
    try:
        base = Path(base_dir).resolve()
        target = Path(target_path).resolve()
        return base in target.parents or base == target
    except (ValueError, OSError):
        return False

def open_in_explorer(path: str) -> bool:
    """在系统文件管理器中打开文件所在目录并选中该文件。

    文件已缺失时退化为打开父目录；父目录也不存在则返回 False。
    """
    import subprocess
    import sys

    if os.path.exists(path):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return True

    parent = os.path.dirname(path)
    if parent and os.path.isdir(parent):
        if sys.platform == "win32":
            os.startfile(parent)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", parent])
        else:
            subprocess.Popen(["xdg-open", parent])
        return True
    return False

def get_video_first_frame(video_path: str, md5_hash: str | None = None) -> str | None:
    """
    通用媒体缩略图生成器：支持视频首帧提取和图片缩放。
    """
    if not md5_hash:
        return None
        
    thumb_filename = f"{md5_hash}.jpg"
    save_path = os.path.join(str(THUMBNAIL_DIR), thumb_filename)
    
    # 1. 检查缓存是否已存在
    if os.path.exists(save_path):
        return save_path

    ext = video_path.split('.')[-1].lower()
    image_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico'}
    
    # 2. 如果是图片，直接读取并缩放
    if ext in image_exts:
        try:
            # OpenCV 读取中文路径可能需要特殊处理，这里假设路径正常或使用 imdecode
            img = cv2.imdecode(np.fromfile(video_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                height, width = img.shape[:2]
                if width > THUMBNAIL_MAX_WIDTH:
                    ratio = THUMBNAIL_MAX_WIDTH / width
                    new_width = THUMBNAIL_MAX_WIDTH
                    new_height = int(height * ratio)
                    img = cv2.resize(img, (new_width, new_height))
                
                # 保存为 JPEG
                is_success, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if is_success:
                    buf.tofile(save_path)
                    return save_path
        except Exception as e:
            print(f"处理图片缩略图失败: {e}")

    # 3. 如果是视频，提取第一帧
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
            
        ret, frame = cap.read()
        cap.release()
        
        if ret and frame is not None:
            height, width = frame.shape[:2]
            if width > THUMBNAIL_MAX_WIDTH:
                ratio = THUMBNAIL_MAX_WIDTH / width
                new_width = THUMBNAIL_MAX_WIDTH
                new_height = int(height * ratio)
                frame = cv2.resize(frame, (new_width, new_height))
            
            is_success, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if is_success:
                buf.tofile(save_path)
                return save_path
    except Exception as e:
        print(f"提取视频帧失败: {e}")
        
    return None