# === 文件路径: tests/test_scanner.py ===
"""扫描引擎冒烟：新增 / 增量跳过 / 变更更新 / 类型白名单。"""
from __future__ import annotations

from src.core.scanner import FileScanner
from src.db.dao import FileDAO
from src.db.database import DatabaseManager


def _run_scanner(targets, incremental=True, exts=None, tmp=None):
    results = []
    scanner = FileScanner(
        targets,
        is_incremental=incremental,
        include_exts=exts,
        on_progress=lambda *a: None,
        on_finished=lambda added, updated: results.append((added, updated)),
    )
    scanner.start()
    scanner.join(timeout=120)
    assert not scanner.is_alive(), "scanner thread did not finish in time"
    return results


def test_scan_add_files_and_incremental(temp_db, tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    (src / "b.txt").write_text("world", encoding="utf-8")
    (src / "skip.exe").write_text("ignored", encoding="utf-8")

    # 全量扫描，白名单只收 .txt
    results = _run_scanner([str(src)], incremental=False, exts={".txt"})
    assert results == [(2, 0)]

    dao = FileDAO(DatabaseManager())
    files, total = dao.get_files_page(1, 50)
    assert total == 2
    rec = next(f for f in files if f.name == "a.txt")
    assert rec.md5 and len(rec.md5) == 32
    assert rec.file_type == "document"
    assert rec.md5_state == 1

    # 增量重扫（同样带白名单）：无变化
    results = _run_scanner([str(src)], incremental=True, exts={".txt"})
    assert results == [(0, 0)]

    # 修改其中一个文件：更新 1 个
    (src / "a.txt").write_text("changed content", encoding="utf-8")
    results = _run_scanner([str(src)], incremental=True, exts={".txt"})
    assert results == [(0, 1)]

    files, total = dao.get_files_page(1, 50)
    assert total == 2  # skip.exe 始终未被索引


def test_scan_default_whitelist_excludes_executables(temp_db, tmp_path):
    src = tmp_path / "mixed"
    src.mkdir()
    (src / "a.txt").write_text("text", encoding="utf-8")
    (src / "b.exe").write_bytes(b"MZ")

    _run_scanner([str(src)], incremental=False)  # 未指定类型 → 走默认白名单
    _, total = FileDAO(DatabaseManager()).get_files_page(1, 50)
    assert total == 1


def test_scan_marks_and_restores_missing(temp_db, tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    b = src / "b.txt"
    b.write_text("world", encoding="utf-8")

    _run_scanner([str(src)], incremental=True, exts={".txt"})
    dao = FileDAO(DatabaseManager())
    assert dao.count_missing() == 0

    # 删除后重扫：标记失联而非删除记录
    b.unlink()
    _run_scanner([str(src)], incremental=True, exts={".txt"})
    assert dao.count_missing() == 1
    rec = dao.get_file_by_path(str(b.resolve()))
    assert rec is not None and rec.missing == 1

    # 文件恢复后重扫：自动恢复正常
    b.write_text("world", encoding="utf-8")
    _run_scanner([str(src)], incremental=True, exts={".txt"})
    assert dao.count_missing() == 0
    rec = dao.get_file_by_path(str(b.resolve()))
    assert rec is not None and rec.missing == 0
