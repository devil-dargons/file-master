# === 文件路径: src/core/consolidation.py ===
"""归集区（开发手册 5.7）：把索引中的文件以硬链接收拢到统一目录树。

- 结构：`<归集目标>/<大类>/<年份>/<文件名>`；年份优先取拍摄时间，否则取修改时间
- `os.link` 失败（跨卷 / 文件系统不支持）→ `shutil.copy2` 回退，结果中分别计数
- 成功记录写入 `consolidated_links`；提供「修复链接」（链接丢失时按源重建）
- 本模块无 Qt 依赖；耗时操作由 UI 层放入后台线程
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.core.models import FileRecord
from src.db.dao import ConsolidatedLinkDAO, FileDAO

logger = logging.getLogger(__name__)

CATEGORY_DIRS = {
    "image": "图片",
    "video": "视频",
    "audio": "音频",
    "document": "文档",
    "archive": "压缩包",
    "other": "其他",
}


@dataclass
class ConsolidateResult:
    """归集/修复操作统计。"""

    linked: int = 0      # 硬链接成功
    copied: int = 0      # 回退复制成功
    skipped: int = 0     # 目标已存在 / 源缺失 / 重复记录
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
        parts = [f"硬链接 {self.linked}"]
        if self.copied:
            parts.append(f"复制回退 {self.copied}")
        if self.skipped:
            parts.append(f"跳过 {self.skipped}")
        if self.failed:
            parts.append(f"失败 {self.failed}")
        return "，".join(parts)


def make_link_or_copy(src: Path, dest: Path) -> None:
    """优先硬链接（同卷免拷贝），失败回退 copy2。"""
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


class ConsolidationService:
    """归集区门面服务（同步方法，UI 负责放后台线程）。"""

    def __init__(self, file_dao: FileDAO, link_dao: ConsolidatedLinkDAO):
        self._files = file_dao
        self._links = link_dao

    # ==========================================
    # 归集
    # ==========================================
    def consolidate(self, records: list[FileRecord], target_root: str,
                    on_progress=None) -> ConsolidateResult:
        """把给定记录归集到目标目录；返回统计。on_progress(done, total) 可选。"""
        result = ConsolidateResult()
        root = Path(target_root)
        total = len(records)
        for done, record in enumerate(records, 1):
            if on_progress is not None and done % 20 == 0:
                on_progress(done, total)
            if record.missing or not os.path.isfile(record.path):
                result.skipped += 1
                continue
            dest = self._plan_dest(record, root)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    result.skipped += 1
                    continue
                make_link_or_copy(Path(record.path), dest)
                if self._links.add_link(record.id, str(dest)) < 0:
                    result.failed += 1
                    result.errors.append(f"记录失败：{record.name}")
                    continue
                if dest.samefile(Path(record.path)):
                    result.linked += 1
                else:
                    result.copied += 1
            except OSError as e:
                result.failed += 1
                result.errors.append(f"{record.name}: {e}")
                logger.warning("Consolidate failed for %s: %s", record.path, e)
        if on_progress is not None:
            on_progress(total, total)
        logger.info("Consolidation done: %s", result.summary())
        return result

    def _plan_dest(self, record: FileRecord, root: Path) -> Path:
        category = CATEGORY_DIRS.get(record.file_type, CATEGORY_DIRS["other"])
        year = self._resolve_year(record)
        return root / category / year / record.name

    def _resolve_year(self, record: FileRecord) -> str:
        """年份优先取拍摄时间（file_meta.shot_time），否则取文件修改时间。"""
        try:
            meta = self._files.get_file_meta(record.id)
        except Exception:
            meta = None
        if meta and meta.shot_time and len(meta.shot_time) >= 4:
            return meta.shot_time[:4]
        return time.strftime("%Y", time.localtime(record.modified_time))

    # ==========================================
    # 修复链接
    # ==========================================
    def repair_links(self, on_progress=None) -> ConsolidateResult:
        """检查全部归集链接：链接丢失但源文件仍在 → 重建；源也没了 → 清理记录。"""
        result = ConsolidateResult()
        links = self._links.list_links()
        total = len(links)
        for done, link in enumerate(links, 1):
            if on_progress is not None and done % 20 == 0:
                on_progress(done, total)
            link_path = Path(link.link_path)
            if link_path.exists():
                result.skipped += 1
                continue
            record = self._files.get_file_by_id(link.file_id)
            if record is None or not os.path.isfile(record.path):
                self._links.delete_link(link.id)
                result.skipped += 1
                continue
            try:
                link_path.parent.mkdir(parents=True, exist_ok=True)
                make_link_or_copy(Path(record.path), link_path)
                if link_path.samefile(Path(record.path)):
                    result.linked += 1
                else:
                    result.copied += 1
            except OSError as e:
                result.failed += 1
                result.errors.append(f"{record.name}: {e}")
        if on_progress is not None:
            on_progress(total, total)
        logger.info("Link repair done: %s", result.summary())
        return result
