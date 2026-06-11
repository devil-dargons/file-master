from __future__ import annotations

import sqlite3
import threading
import logging
from src.config import DB_PATH

# ... 下面的代码保持不变 ...
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
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._conn = None
        self._init_db()

    def _init_db(self):
        try:
            self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row 
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._create_tables()
            logger.info("Database initialized successfully at %s", DB_PATH)
        except sqlite3.Error as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def _create_tables(self):
        cursor = self._conn.cursor()
        try:
            # 1. 文件表 (增加了 thumbnail_path)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_time REAL NOT NULL,
                    md5 TEXT NOT NULL,
                    added_time REAL NOT NULL,
                    thumbnail_path TEXT DEFAULT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified_time)")
            
            # 2. 标签表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag_name TEXT NOT NULL UNIQUE
                )
            """)
            
            # 3. 关联表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_tags (
                    file_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (file_id, tag_id),
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id)")

            # 4. 【新增】设置表：用于持久化用户偏好
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            # 初始化默认分页大小为 50
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('page_size', '50')")
            
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error("Failed to create tables: %s", e)
            self._conn.rollback()
            raise

    def get_connection(self) -> sqlite3.Connection:
        if not self._conn:
            self._init_db()
        return self._conn

    def execute_transaction(self, sql_script: str, params: tuple | list = ()) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if isinstance(params, list) and all(isinstance(p, (tuple, list)) for p in params):
                cursor.executemany(sql_script, params)
            else:
                cursor.execute(sql_script, params)
            conn.commit()
            return True
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Transaction failed: %s | SQL: %s", e, sql_script)
            return False