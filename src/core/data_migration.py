# === 文件路径: src/core/data_migration.py ===
"""数据目录迁移（开发手册 5.1）。

流程：预检查 → 关闭本线程连接 → backup API 迁移 db → 子目录逐文件复制
（临时名→原子改名）→ 校验（integrity_check + 记录数一致）→ 写指针文件与
marker；失败任意一步 → 清理新目录半成品，旧目录保持原样。
迁移后需重启应用（本进程内 config 路径不再变更）。

UI 层职责：调用前暂停全部后台任务（扫描/元数据/缩略图线程）。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import config
from src.core.maintenance import dir_stats
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

# 需要逐文件复制的子目录（logs 不迁移，新目录重建）
MIGRATE_SUBDIRS = ["thumbnails", "vault", "backups"]
MIN_FREE_MARGIN = 64 * 1024 * 1024  # 至少再留 64MB 余量


@dataclass
class MigrationResult:
    success: bool
    message: str
    new_dir: str = ""


class DataDirMigrator:
    """数据目录迁移门面（同步方法，UI 负责暂停后台任务并放后台线程）。"""

    def __init__(self, db_manager: DatabaseManager, default_root: Path | None = None,
                 current_dir: Path | None = None):
        self._db = db_manager
        self._default_root = Path(default_root) if default_root else config.DEFAULT_DATA_ROOT
        self._current_dir = Path(current_dir) if current_dir else Path(config.APPDATA_DIR)

    # ==========================================
    # 预检查
    # ==========================================
    def precheck(self, new_dir: Path) -> str | None:
        """返回 None 表示通过，否则返回原因文本。"""
        new_dir = Path(new_dir)
        if new_dir.exists() and not new_dir.is_dir():
            return "目标路径是一个文件，不是目录"
        try:
            current = self._current_dir.resolve()
            target = new_dir.resolve()
        except OSError as e:
            return f"无法解析目录路径：{e}"
        if target == current:
            return "新目录与当前数据目录相同"
        if current in target.parents:
            return "新目录不能位于当前数据目录内部"

        # 可写权限
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            probe = new_dir / ".fm_write_probe"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            return f"目标目录不可写：{e}"

        # 剩余空间 ≥ 现用数据大小 × 1.2（且至少留 64MB 余量）
        try:
            used = dir_stats(self._current_dir)[0]
            need = int(used * 1.2) + MIN_FREE_MARGIN
            free = shutil.disk_usage(str(new_dir)).free
            if free < need:
                return (f"剩余空间不足：当前数据 {used / 1e6:.1f} MB，"
                        f"需要约 {need / 1e6:.1f} MB，目标盘仅剩 {free / 1e6:.1f} MB")
        except OSError:
            pass  # 无法估算磁盘空间时跳过该项
        return None

    # ==========================================
    # 迁移
    # ==========================================
    def migrate(self, new_dir: Path, progress=None) -> MigrationResult:
        new_dir = Path(new_dir)
        reason = self.precheck(new_dir)
        if reason:
            return MigrationResult(False, reason)

        new_db = new_dir / "filemaster.db"
        old_db = Path(config.DB_PATH)
        try:
            if progress:
                progress("迁移数据库…")
            self._db.close_thread_connection()  # 保证 backup 一致性（后台任务已由 UI 暂停）
            src_conn = sqlite3.connect(str(old_db))
            dst_conn = sqlite3.connect(str(new_db))
            try:
                with dst_conn:
                    src_conn.backup(dst_conn)
            finally:
                src_conn.close()
                dst_conn.close()

            if progress:
                progress("复制数据文件…")
            self._copy_subdirs(new_dir, progress)

            if progress:
                progress("校验…")
            self._verify(old_db, new_db)

            if progress:
                progress("写入目录指针…")
            pointer = self._default_root / config.POINTER_FILE_NAME
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text(str(new_dir.resolve()), encoding="utf-8")
            (new_dir / ".datadir_marker").write_text(config.APP_VERSION, encoding="utf-8")

            logger.info("Data dir migrated to %s", new_dir.resolve())
            return MigrationResult(True, "迁移完成，请重启应用生效", str(new_dir.resolve()))
        except Exception as e:
            logger.exception("Data dir migration failed")
            self._cleanup_partial(new_dir)
            return MigrationResult(False, f"迁移失败，已回滚（旧目录完好）：{e}")

    def _copy_subdirs(self, new_dir: Path, progress=None) -> None:
        for sub in MIGRATE_SUBDIRS:
            src_dir = self._current_dir / sub
            if not src_dir.is_dir():
                continue
            dst_dir = new_dir / sub
            dst_dir.mkdir(parents=True, exist_ok=True)
            files = [f for f in src_dir.rglob("*") if f.is_file()]
            total = len(files)
            for done, f in enumerate(files, 1):
                if progress and done % 50 == 0:
                    progress(f"复制 {sub}… {done}/{total}")
                dest_f = dst_dir / f.relative_to(src_dir)
                dest_f.parent.mkdir(parents=True, exist_ok=True)
                tmp_f = dest_f.with_suffix(dest_f.suffix + ".fmmig")
                shutil.copy2(f, tmp_f)
                os.replace(tmp_f, dest_f)

    @staticmethod
    def _verify(old_db: Path, new_db: Path) -> None:
        conn = sqlite3.connect(str(new_db))
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"新库完整性校验失败：{check}")
            counts_new = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("files", "tags"))
        finally:
            conn.close()
        conn = sqlite3.connect(str(old_db))
        try:
            counts_old = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("files", "tags"))
        finally:
            conn.close()
        if counts_new != counts_old:
            raise RuntimeError(f"迁移后记录数不一致 files/tags：{counts_old} → {counts_new}")

    @staticmethod
    def _cleanup_partial(new_dir: Path) -> None:
        """回滚：只清理本次迁移生成的半成品，不动目录内既有文件。"""
        for sub in MIGRATE_SUBDIRS:
            shutil.rmtree(new_dir / sub, ignore_errors=True)
        for name in ("filemaster.db", "filemaster.db-wal", "filemaster.db-shm",
                     ".datadir_marker"):
            try:
                (new_dir / name).unlink(missing_ok=True)
            except OSError:
                pass
