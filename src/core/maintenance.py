# === 文件路径: src/core/maintenance.py ===
"""缓存维护（开发手册 5.9）：目录占用统计、缩略图清理。

纯函数无 Qt 依赖；VACUUM 由 db 层提供。
"""
from __future__ import annotations

from pathlib import Path


def dir_stats(path: Path) -> tuple[int, int]:
    """返回（总字节，文件数）。"""
    total, count = 0, 0
    root = Path(path)
    if not root.exists():
        return 0, 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def clear_thumbnail_cache(thumb_dir: Path) -> int:
    """清理缩略图缓存（*.jpg），返回删除的文件数。"""
    removed = 0
    for p in Path(thumb_dir).glob("*.jpg"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            continue
    return removed
