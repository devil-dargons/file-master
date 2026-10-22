# === 文件路径: src/core/exporter.py ===
"""CSV 报表导出（开发手册 5.7）：把筛选结果导出为 Excel 友好的 UTF-8-BOM CSV。

纯函数无 Qt 依赖；标签等展示字段由调用方填充到 FileRecord。
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

from src.core.models import FileRecord

CSV_HEADERS = ["名称", "类型", "大小(字节)", "修改时间", "路径", "MD5", "标签", "状态"]


def export_csv(records: list[FileRecord], out_path: str) -> Path:
    """导出记录列表到 CSV；返回输出路径。"""
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for r in records:
            writer.writerow([
                r.name,
                r.file_type,
                r.size,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.modified_time)),
                r.path,
                r.md5,
                r.tags_str,
                "已失联" if r.missing else "正常",
            ])
    return dest


def default_csv_name(prefix: str = "filemaster") -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
