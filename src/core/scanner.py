# === 文件路径: src/core/scanner.py ===
"""扫描引擎：纯 threading 实现，不感知 Qt。

进度通过构造时注入的回调上报（on_progress / on_finished），
UI 层在 qt_bridge 中把回调转成 Qt Signal。
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from src.config import MD5_CHUNK_SIZE, DB_BATCH_SIZE
from src.core.classifier import SUPPORTED_EXTS, classify_path
from src.core.models import FileRecord
from src.core.tag_service import TagRuleEngine
from src.db.dao import FileDAO
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int, str], None]]   # (current, total, path)
FinishedCallback = Optional[Callable[[int, int], None]]        # (added, updated)


class FileScanner(threading.Thread):
    """增量文件扫描线程。

    - 不再继承 QThread；UI 通过回调接收进度（经 qt_bridge 转信号）
    - 增量判重：path -> (size, mtime) 未变则跳过，不重算 MD5
    - 入库时记录 file_type，MD5 已算出则置 md5_state=1
    """

    def __init__(
        self,
        target_paths: list[str],
        is_incremental: bool = True,
        include_exts: Optional[set[str]] = None,
        on_progress: ProgressCallback = None,
        on_finished: FinishedCallback = None,
    ):
        super().__init__(daemon=True, name="FileScanner")
        self.target_paths = target_paths
        self.is_incremental = is_incremental
        self.include_exts = {ext.lower() for ext in include_exts} if include_exts else None
        self._stop_event = threading.Event()
        self._touched_paths: set[str] = set()  # 本次新增/更新的路径（用于自动打标）

        self.on_progress = on_progress
        self.on_finished = on_finished

        self.db_manager = DatabaseManager()
        self.file_dao = FileDAO(self.db_manager)

    # ----------------------------------
    # 对外控制
    # ----------------------------------
    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set() and self.is_alive()

    # ----------------------------------
    # 主体逻辑
    # ----------------------------------
    def run(self) -> None:
        added_count = 0
        updated_count = 0
        current_index = 0

        db_cache = self.file_dao.get_path_cache() if self.is_incremental else {}
        batch_buffer: list[FileRecord] = []
        seen_paths: set[str] = set()
        completed_roots: list[str] = []

        for target in self.target_paths:
            if self._stop_event.is_set():
                break

            target_path = Path(target)
            if target_path.is_file():
                seen_paths.add(str(target_path.resolve()))
                if self._should_scan(target_path):
                    res = self._process_file(target_path, db_cache, batch_buffer)
                    if res == 1:
                        added_count += 1
                    elif res == 2:
                        updated_count += 1
                    current_index += 1
                completed_roots.append(str(target_path))
            elif target_path.is_dir():
                root_completed = True
                for root, _, files in os.walk(target_path):
                    if self._stop_event.is_set():
                        root_completed = False
                        break
                    for file_name in files:
                        file_path = Path(root) / file_name
                        # 目录里实际存在的文件都算"已见到"，即使被白名单排除也不判失联
                        seen_paths.add(str(file_path.resolve()))
                        # 在加入处理队列前进行类型过滤
                        if self._should_scan(file_path):
                            res = self._process_file(file_path, db_cache, batch_buffer)
                            if res == 1:
                                added_count += 1
                            elif res == 2:
                                updated_count += 1

                            current_index += 1
                            if current_index % 10 == 0:
                                self._report_progress(current_index, str(file_path))

                            if len(batch_buffer) >= DB_BATCH_SIZE:
                                self._flush_batch(batch_buffer)
                if root_completed:
                    completed_roots.append(str(target_path))

        if batch_buffer:
            self._flush_batch(batch_buffer)

        # 失联判定：仅对完整扫描过的根目录执行，被中断的扫描不判定
        missing_count = 0
        if completed_roots and not self._stop_event.is_set():
            missing_count = self.file_dao.mark_missing(completed_roots, seen_paths)

        # L1 自动打标：对本次新增/更新的文件应用启用中的规则
        if self._touched_paths and not self._stop_event.is_set():
            try:
                applied = TagRuleEngine(self.db_manager).apply_to_paths(list(self._touched_paths))
                if applied:
                    logger.info("Auto tag rules applied to %d bindings", applied)
            except Exception:
                logger.exception("Apply auto tag rules failed")

        logger.info(
            f"Scan finished. Added: {added_count}, Updated: {updated_count}, Missing: {missing_count}")
        self._report_finished(added_count, updated_count)

    def _should_scan(self, file_path: Path) -> bool:
        """类型白名单过滤：未指定时按 classifier.SUPPORTED_EXTS 收窄，不索引系统/可执行文件。"""
        exts = self.include_exts or SUPPORTED_EXTS
        return file_path.suffix.lower() in exts

    def _process_file(self, file_path: Path, db_cache: dict, batch_buffer: list) -> int:
        """处理单个文件。返回 0=跳过 1=新增 2=更新"""
        try:
            abs_path = str(file_path.resolve())
            stat = file_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime

            if self.is_incremental and abs_path in db_cache:
                cached = db_cache[abs_path]
                if cached.size == size and cached.modified_time == mtime:
                    # 记录此前被判失联但文件已恢复 → 恢复正常状态
                    if cached.missing:
                        self.file_dao.set_missing(abs_path, 0)
                        cached.missing = 0
                    # 自愈：老数据 file_type 为 other（历史版本未写入）→ 顺带修正，
                    # 否则元数据提取的 pending 查询永远选不中这些文件
                    correct_type = classify_path(abs_path)
                    if cached.file_type != correct_type:
                        self.file_dao.update_file_type(abs_path, correct_type)
                        cached.file_type = correct_type
                    return 0

            md5 = self._calculate_md5(abs_path)
            if not md5:
                return 0

            record = FileRecord(
                id=0,
                path=abs_path,
                name=file_path.name,
                size=size,
                modified_time=mtime,
                md5=md5,
                added_time=time.time(),
                file_type=classify_path(abs_path),
                md5_state=1,
            )

            if abs_path in db_cache:
                self.file_dao.update_file_info(abs_path, record)
                db_cache[abs_path] = record
                self._touched_paths.add(abs_path)
                return 2

            batch_buffer.append(record)
            db_cache[abs_path] = record
            self._touched_paths.add(abs_path)
            return 1

        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.debug(f"Skip file {file_path}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error processing {file_path}: {e}")
            return 0

    def _calculate_md5(self, file_path: str) -> Optional[str]:
        md5_hash = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(MD5_CHUNK_SIZE), b""):
                    if self._stop_event.is_set():
                        return None
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Cannot read file for MD5: {file_path} | {e}")
            return None

    def _flush_batch(self, batch_buffer: list) -> None:
        if not batch_buffer:
            return
        inserted = self.file_dao.insert_files_batch(batch_buffer)
        logger.debug(f"Batch inserted {inserted} files.")
        batch_buffer.clear()

    # ----------------------------------
    # 回调上报（隔离异常，防止回调错误中断扫描）
    # ----------------------------------
    def _report_progress(self, current: int, path: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(current, 0, path)
            except Exception:
                logger.exception("on_progress callback failed")

    def _report_finished(self, added: int, updated: int) -> None:
        if self.on_finished:
            try:
                self.on_finished(added, updated)
            except Exception:
                logger.exception("on_finished callback failed")

