# === 文件路径: tests/test_data_dir_migration.py ===
"""M7 数据目录测试（开发手册 5.1）：

- config 路径解析链：参数 / 环境变量 / portable.flag / 指针文件 / 默认
- 数据目录迁移：预检查、迁移 + 校验 + 指针写入、失败回滚（旧目录完好）
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from src import config as config_mod
from src.core.data_migration import DataDirMigrator
from src.db.database import DatabaseManager


# ==========================================
# 路径解析链（纯函数）
# ==========================================
def test_resolve_data_dir_cli_arg_highest_priority():
    p = config_mod.resolve_data_dir(
        argv=["app", "--data-dir", "D:/custom"],
        env={"FILEMASTER_DATA_DIR": "D:/env"},
        base_dir=None, default_root=None)
    assert p.name == "custom"


def test_resolve_data_dir_env_var():
    p = config_mod.resolve_data_dir(
        argv=[], env={"FILEMASTER_DATA_DIR": "D:/from-env"},
        default_root=None)
    assert p == Path("D:/from-env")


def test_resolve_data_dir_portable_flag(tmp_path):
    (tmp_path / "portable.flag").write_text("")
    p = config_mod.resolve_data_dir(argv=[], env={}, base_dir=tmp_path)
    assert p == tmp_path / "data"


def test_resolve_data_dir_pointer_file(tmp_path):
    target = tmp_path / "moved"
    target.mkdir()
    (tmp_path / "pointer_home" / "FileMaster").mkdir(parents=True)
    pointer = tmp_path / "pointer_home" / "FileMaster" / "data_location.txt"
    pointer.write_text(str(target.resolve()), encoding="utf-8")
    p = config_mod.resolve_data_dir(
        argv=[], env={}, default_root=tmp_path / "pointer_home" / "FileMaster")
    assert p == target.resolve()


def test_resolve_data_dir_default(tmp_path):
    p = config_mod.resolve_data_dir(argv=[], env={}, default_root=tmp_path)
    assert p == tmp_path


def test_resolve_data_dir_invalid_pointer_falls_back(tmp_path):
    (tmp_path / "data_location.txt").write_text("not-absolute", encoding="utf-8")
    p = config_mod.resolve_data_dir(argv=[], env={}, default_root=tmp_path)
    assert p == tmp_path


# ==========================================
# 数据目录迁移
# ==========================================
@pytest.fixture
def migrator_env(temp_db, tmp_path, monkeypatch):
    """构造「当前数据目录」= fake_current，config 指向它；默认根 = default_root。"""
    fake_current = tmp_path / "current_data"
    default_root = tmp_path / "pointer_home" / "FileMaster"
    fake_current.mkdir(parents=True)
    default_root.mkdir(parents=True)

    # 让 DatabaseManager 的库文件建到 fake_current
    monkeypatch.setattr(config_mod, "DB_PATH", fake_current / "filemaster.db")
    DatabaseManager._instance = None
    db = DatabaseManager()
    # 造两条 files + 一条 tags 数据
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO files (path, name, size, modified_time, md5, added_time) "
        "VALUES ('/x/a.jpg', 'a.jpg', 1, ?, '', ?)", (time.time(), time.time()))
    conn.execute(
        "INSERT INTO files (path, name, size, modified_time, md5, added_time) "
        "VALUES ('/x/b.jpg', 'b.jpg', 2, ?, '', ?)", (time.time(), time.time()))
    conn.execute("INSERT INTO tags (tag_name) VALUES ('测试')")
    conn.commit()

    # 造缩略图缓存文件
    thumbs = fake_current / "thumbnails"
    thumbs.mkdir(exist_ok=True)
    (thumbs / "abc.jpg").write_bytes(b"thumb")
    (fake_current / "vault").mkdir(exist_ok=True)
    (fake_current / "vault" / "enc.fmv").write_bytes(b"cipher")

    migrator = DataDirMigrator(db, default_root=default_root, current_dir=fake_current)
    return db, migrator, fake_current, default_root


def test_migration_precheck_rejects_inner_dir(migrator_env, tmp_path):
    _, migrator, fake_current, _ = migrator_env
    assert migrator.precheck(fake_current / "inner") is not None
    assert migrator.precheck(fake_current) is not None
    assert migrator.precheck(tmp_path / "fresh") is None


def test_migration_success_and_pointer(migrator_env, tmp_path):
    _, migrator, fake_current, default_root = migrator_env
    target = tmp_path / "new_home"

    result = migrator.migrate(target)

    assert result.success, result.message
    # 数据库迁移且记录数一致
    conn = sqlite3.connect(str(target / "filemaster.db"))
    try:
        files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        tags_n = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert (files_n, tags_n) == (2, 1)
    # 子目录文件复制
    assert (target / "thumbnails" / "abc.jpg").read_bytes() == b"thumb"
    assert (target / "vault" / "enc.fmv").read_bytes() == b"cipher"
    # 指针文件写入默认根
    pointer = default_root / "data_location.txt"
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8") == str(target.resolve())
    # marker
    assert (target / ".datadir_marker").is_file()


def test_migration_failure_rolls_back_old_dir_intact(migrator_env, tmp_path, monkeypatch):
    """迁移中途失败：新目录半成品被清理，旧目录数据完好可用（手册 5.1 验收）。"""
    db, migrator, fake_current, _ = migrator_env
    target = tmp_path / "failed_home"
    # 破坏校验环节：让 _verify 抛错
    monkeypatch.setattr(DataDirMigrator, "_verify",
                        staticmethod(lambda old, new: (_ for _ in ()).throw(RuntimeError("boom"))))

    result = migrator.migrate(target)

    assert not result.success
    assert "boom" in result.message
    # 半成品已清理
    assert not (target / "filemaster.db").exists()
    assert not (target / "thumbnails").exists()
    # 旧目录完好可查
    conn = sqlite3.connect(str(fake_current / "filemaster.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2
    finally:
        conn.close()
    # 指针未写入
    assert not (tmp_path / "pointer_home" / "FileMaster" / "data_location.txt").exists()


def test_kill_process_during_migration_leaves_old_dir_usable(temp_db, tmp_path, monkeypatch):
    """模拟 kill 进程：backup 半途被杀（不写指针）→ 重启仍解析到旧目录且数据完好。"""
    import shutil

    default_root = tmp_path / "pointer_home" / "FileMaster"
    default_root.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "DB_PATH", default_root / "filemaster.db")
    DatabaseManager._instance = None
    db = DatabaseManager()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO files (path, name, size, modified_time, md5, added_time) "
        "VALUES ('/x/a.jpg', 'a.jpg', 1, ?, '', ?)", (time.time(), time.time()))
    conn.commit()

    # backup 半成品（模拟迁移被 kill，指针从未写入）
    target = tmp_path / "kill_home"
    target.mkdir()
    shutil.copy2(default_root / "filemaster.db", target / "filemaster.db")

    # 指针不存在 → 重启后仍解析到旧目录
    assert config_mod.resolve_data_dir(argv=[], env={}, default_root=default_root) == default_root
    # 旧目录数据完好可用
    conn2 = sqlite3.connect(str(default_root / "filemaster.db"))
    try:
        assert conn2.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        assert conn2.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn2.close()
