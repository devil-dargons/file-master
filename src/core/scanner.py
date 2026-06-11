# === 文件路径: src/core/scanner.py ===
from __future__ import annotations
import os
import hashlib
import time
import logging
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QThread

from src.config import MD5_CHUNK_SIZE, DB_BATCH_SIZE
from src.db.database_manager import DatabaseManager
from src.db.dao import FileDAO
from src.core.signals import AppSignals

logger = logging.getLogger(__name__)

class FileScanner(QThread):
    def __init__(self, target_paths: list[str], is_incremental: bool = True, include_exts: set[str] = None):
        super().__init__()
        self.target_paths = target_paths
        self.is_incremental = is_incremental
        # 将扩展名集合转为小写，方便比对
        self.include_exts = {ext.lower() for ext in include_exts} if include_exts else None
        self._is_running = True
        
        self.db_manager = DatabaseManager()
        self.file_dao = FileDAO(self.db_manager)
        self.signals = AppSignals()

    def stop(self):
        self._is_running = False

    def run(self):
        added_count = 0
        updated_count = 0
        current_index = 0
        
        db_cache = self._load_db_cache() if self.is_incremental else {}
        batch_buffer = []

        for target in self.target_paths:
            if not self._is_running: break
            
            target_path = Path(target)
            if target_path.is_file():
                if self._should_scan(target_path):
                    res = self._process_file(target_path, db_cache, batch_buffer)
                    if res == 1: added_count += 1
                    elif res == 2: updated_count += 1
                    current_index += 1
            elif target_path.is_dir():
                for root, _, files in os.walk(target_path):
                    if not self._is_running: break
                    for file_name in files:
                        file_path = Path(root) / file_name
                        # 核心：在加入处理队列前进行类型过滤
                        if self._should_scan(file_path):
                            res = self._process_file(file_path, db_cache, batch_buffer)
                            if res == 1: added_count += 1
                            elif res == 2: updated_count += 1
                            
                            current_index += 1
                            if current_index % 10 == 0:
                                self.signals.scan_progress.emit(current_index, 0, str(file_path))
                                
                            if len(batch_buffer) >= DB_BATCH_SIZE:
                                self._flush_batch(batch_buffer)

        if batch_buffer:
            self._flush_batch(batch_buffer)
            
        logger.info(f"Scan finished. Added: {added_count}, Updated: {updated_count}")
        self.signals.scan_finished.emit(added_count, updated_count)

    def _should_scan(self, file_path: Path) -> bool:
        """判断文件是否应该被扫描"""
        if not self.include_exts:
            return True
        return file_path.suffix.lower() in self.include_exts

    def _load_db_cache(self) -> dict:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT path, size, modified_time, md5 FROM files")
            return {row['path']: dict(row) for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to load DB cache: {e}")
            return {}

    def _process_file(self, file_path: Path, db_cache: dict, batch_buffer: list) -> int:
        try:
            abs_path = str(file_path.resolve())
            stat = file_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            
            if self.is_incremental and abs_path in db_cache:
                cached = db_cache[abs_path]
                if cached['size'] == size and cached['modified_time'] == mtime:
                    return 0
            
            md5 = self._calculate_md5(abs_path)
            if not md5: return 0
                
            file_info = {
                'path': abs_path,
                'name': file_path.name,
                'size': size,
                'modified_time': mtime,
                'md5': md5,
                'added_time': time.time()
            }
            
            if abs_path in db_cache:
                self.file_dao.update_file_info(abs_path, file_info)
                db_cache[abs_path] = file_info
                return 2
            else:
                batch_buffer.append(file_info)
                db_cache[abs_path] = file_info
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
                    if not self._is_running: return None
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Cannot read file for MD5: {file_path} | {e}")
            return None

    def _flush_batch(self, batch_buffer: list):
        if not batch_buffer: return
        inserted = self.file_dao.insert_files_batch(batch_buffer)
        logger.debug(f"Batch inserted {inserted} files.")
        batch_buffer.clear()