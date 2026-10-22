# === 文件路径: src/db/database.py ===
"""SQLite 连接管理：每线程独立连接 + WAL 模式（开发手册 4.4）。

- 连接绑定 threading.local，同一连接只在其创建线程内使用（check_same_thread 保持默认 True）
- WAL + busy_timeout 支持后台线程（扫描/缩略图）与 UI 线程并发读写
- 首次初始化时自动执行迁移（PRAGMA user_version 驱动）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from src import config
from src.db.migrations import runner

logger = logging.getLogger(__name__)


class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._local = threading.local()
        self.db_path = Path(config.DB_PATH)
        self._migrate()
        logger.info("Database initialized at %s", self.db_path)

    # ----------------------------------
    # 连接管理
    # ----------------------------------
    def get_connection(self) -> sqlite3.Connection:
        """返回当前线程的独立连接；不存在则创建并应用 PRAGMA。"""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._local.conn = conn
        return conn

    def close_thread_connection(self) -> None:
        """关闭当前线程的连接（线程退出前调用，可选）。"""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    # ----------------------------------
    # 迁移
    # ----------------------------------
    def _migrate(self) -> None:
        try:
            version = runner.run_migrations(self.db_path)
            logger.info("Schema version: %d", version)
        except sqlite3.Error as e:
            logger.error("Migration failed: %s", e)
            raise
        self._heal_file_types()

    def _heal_file_types(self) -> None:
        """数据自愈：历史记录在 file_type 列引入前入库（全为 'other'），按扩展名重算修正。

        幂等：已修正的行不再命中 WHERE，启动开销趋近于零。
        不修正会导致元数据提取的 pending 查询（file_type IN ...）永远选不中这些文件。
        """
        from src.core.classifier import classify_path
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name FROM files "
                "WHERE file_type IS NULL OR file_type = '' OR file_type = 'other'")
            rows = cursor.fetchall()
            if not rows:
                return
            updates = [
                (t, row["id"]) for row in rows
                if (t := classify_path(row["name"])) != "other"
            ]
            if updates:
                cursor.executemany("UPDATE files SET file_type = ? WHERE id = ?", updates)
                conn.commit()
                logger.info("Healed file_type for %d legacy rows", len(updates))
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Heal file_type failed: %s", e)

    # ----------------------------------
    # 便捷写事务
    # ----------------------------------
    def execute_transaction(self, sql: str, params: tuple | list = ()) -> bool:
        """执行单条写语句（params 为 list[tuple] 时走 executemany）。失败回滚并返回 False。"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if isinstance(params, list) and all(isinstance(p, (tuple, list)) for p in params):
                cursor.executemany(sql, params)
            else:
                cursor.execute(sql, params)
            conn.commit()
            return True
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Transaction failed: %s | SQL: %s", e, sql)
            return False

    def vacuum(self) -> bool:
        """整理数据库文件（回收空闲页）。不能在事务中执行。"""
        conn = self.get_connection()
        try:
            conn.commit()
            conn.execute("VACUUM")
            logger.info("Database vacuumed.")
            return True
        except sqlite3.Error as e:
            logger.error("VACUUM failed: %s", e)
            return False
