# === 文件路径: tests/test_migration.py ===
"""迁移机制冒烟：全新库直升 v2；存量 v1 库升级且数据保留。"""
from __future__ import annotations

import sqlite3

from src.db.database import DatabaseManager
from src.db.migrations import runner


def test_fresh_db_migrates_to_v2(temp_db):
    dm = DatabaseManager()
    conn = dm.get_connection()

    version = runner.current_version(conn)
    assert version == 2

    file_cols = {r["name"] for r in conn.execute("PRAGMA table_info(files)")}
    assert {"file_type", "md5_state", "missing"} <= file_cols

    tag_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tags)")}
    assert {"color", "is_auto"} <= tag_cols

    ft_cols = {r["name"] for r in conn.execute("PRAGMA table_info(file_tags)")}
    assert "source" in ft_cols

    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "tags", "file_tags", "settings", "file_meta",
            "auto_rules", "vault_items", "consolidated_links"} <= tables


def test_legacy_v1_db_upgraded_with_data_preserved(temp_db):
    # 手工构造 v1 老库（user_version=0，无 v2 列）
    legacy = sqlite3.connect(str(temp_db))
    legacy.executescript("""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            md5 TEXT NOT NULL,
            added_time REAL NOT NULL,
            thumbnail_path TEXT DEFAULT NULL
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT NOT NULL UNIQUE);
        CREATE TABLE file_tags (
            file_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
            PRIMARY KEY (file_id, tag_id)
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO files (path, name, size, modified_time, md5, added_time)
        VALUES ('C:/legacy/a.txt', 'a.txt', 10, 1000.0, 'abc123', 1000.0);
        INSERT INTO files (path, name, size, modified_time, md5, added_time)
        VALUES ('C:/legacy/b.xyz', 'b.xyz', 20, 1000.0, 'def456', 1000.0);
        INSERT INTO tags (tag_name) VALUES ('旧标签');
        INSERT INTO file_tags (file_id, tag_id) VALUES (1, 1);
    """)
    legacy.commit()
    legacy.close()

    dm = DatabaseManager()
    conn = dm.get_connection()

    assert runner.current_version(conn) == 2

    row = conn.execute(
        "SELECT path, file_type, md5_state, missing FROM files WHERE name = 'a.txt'").fetchone()
    assert row["path"] == "C:/legacy/a.txt"
    # v1 老数据迁移后由自愈逻辑按扩展名重算（.txt → document），不再停留在默认值 other
    assert row["file_type"] == "document"
    assert row["md5_state"] == 0
    assert row["missing"] == 0

    # 无法分类的扩展名保持 other（自愈不强行归类）
    row_b = conn.execute("SELECT file_type FROM files WHERE name = 'b.xyz'").fetchone()
    assert row_b["file_type"] == "other"

    # 迁移前备份已生成（bak-0）
    assert temp_db.with_name(temp_db.name + ".bak-0").exists()


def test_migration_runner_idempotent(temp_db):
    DatabaseManager()  # 首次迁移到 v2
    version = runner.run_migrations(temp_db)  # 再次执行应为无操作
    assert version == 2
