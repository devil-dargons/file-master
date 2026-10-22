# === 文件路径: src/db/migrations/runner.py ===
"""SQL 迁移执行器：基于 PRAGMA user_version 的顺序迁移。

约定（开发手册 4.3）：
- migrations 目录下按 `NNN_描述.sql` 命名，NNN 即目标版本号
- 启动时比对 user_version，逐个执行未应用的迁移；执行后更新版本号
- 存量库迁移前自动做 `filemaster.db.bak-{version}` 一致性备份
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


def _discover() -> list[tuple[int, Path]]:
    """返回 [(目标版本, 文件路径)]，按版本号升序。"""
    found: list[tuple[int, Path]] = []
    for f in MIGRATIONS_DIR.glob("*.sql"):
        m = _MIGRATION_RE.match(f.name)
        if m:
            found.append((int(m.group(1)), f))
    found.sort(key=lambda x: x[0])
    return found


def _backup(db_path: Path, from_version: int) -> Path | None:
    """用 sqlite3 backup API 做一致性备份（兼容 WAL），失败仅告警不阻断。"""
    backup_path = db_path.with_name(f"{db_path.name}.bak-{from_version}")
    try:
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(str(backup_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        logger.info("Migration backup created: %s", backup_path)
        return backup_path
    except sqlite3.Error as e:
        logger.error("Migration backup failed (continuing): %s", e)
        return None


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def run_migrations(db_path: Path) -> int:
    """将 db_path 指向的库迁移到最新版本，返回最终版本号。

    db_path 通过参数传入（运行时取 config.DB_PATH），便于测试隔离。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        version = current_version(conn)
        pending = [(v, f) for v, f in _discover() if v > version]

        if pending:
            # 存量库（已有数据）才需要备份；全新空库跳过
            has_files_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
            ).fetchone()
            if has_files_table:
                _backup(db_path, version)

        for target, file in pending:
            sql = file.read_text(encoding="utf-8")
            try:
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version = {target}")
                logger.info("Migration applied: %s -> user_version=%d", file.name, target)
            except sqlite3.Error:
                logger.exception("Migration failed: %s (user_version stays at %d)", file.name, version)
                raise

        return current_version(conn)
    finally:
        conn.close()
