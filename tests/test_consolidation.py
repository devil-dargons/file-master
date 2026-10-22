# === 文件路径: tests/test_consolidation.py ===
"""M5 归集区与 CSV 导出测试（开发手册 5.7）：

- 归集结构 <目标>/大类/年份/文件名；硬链接 samefile；拍摄年份优先
- 目标冲突/失联跳过；os.link 失败回退 copy2
- 修复链接：丢失重建、源消失清理记录
- CSV 导出：行数、BOM、字段
"""
from __future__ import annotations

import time

import pytest

from src.core.consolidation import CATEGORY_DIRS, ConsolidationService
from src.core.exporter import export_csv
from src.core.models import FileRecord, MediaMeta
from src.db.dao import ConsolidatedLinkDAO, FileDAO
from src.db.database import DatabaseManager

MT_2024 = time.mktime((2024, 5, 1, 12, 0, 0, 0, 0, -1))


@pytest.fixture
def env(temp_db, tmp_path):
    db = DatabaseManager()
    file_dao = FileDAO(db)
    link_dao = ConsolidatedLinkDAO(db)
    svc = ConsolidationService(file_dao, link_dao)
    return file_dao, link_dao, svc, tmp_path


def _insert(file_dao: FileDAO, tmp_path, name: str, data: bytes,
            file_type: str = "image", mtime: float = MT_2024) -> FileRecord:
    src = tmp_path / name
    src.write_bytes(data)
    record = FileRecord(
        id=0, path=str(src), name=name, size=len(data), modified_time=mtime,
        md5="", added_time=time.time(), file_type=file_type,
    )
    file_id = file_dao.insert_file(record)
    record.id = file_id
    return record


# ==========================================
# 归集
# ==========================================
def test_consolidate_hardlink_structure(env):
    file_dao, link_dao, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "photo.jpg", b"jpeg-data")

    target = tmp_path / "consolidated"
    result = svc.consolidate([record], str(target))

    assert result.linked == 1 and result.ok
    dest = target / CATEGORY_DIRS["image"] / "2024" / "photo.jpg"
    assert dest.is_file()
    assert dest.samefile(record.path)          # 硬链接同 inode
    assert dest.read_bytes() == b"jpeg-data"
    links = link_dao.list_links()
    assert len(links) == 1 and links[0].file_id == record.id


def test_consolidate_prefers_shot_year(env):
    file_dao, _, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "cam.jpg", b"x")
    file_dao.upsert_file_meta(record.id, MediaMeta(shot_time="2023-07-01T10:00:00"), 0, "image")

    target = tmp_path / "out"
    result = svc.consolidate([record], str(target))
    assert result.linked == 1
    assert (target / "图片" / "2023" / "cam.jpg").is_file()


def test_consolidate_skips_existing_and_missing(env):
    file_dao, _, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "a.png", b"a")
    missing_record = FileRecord(
        id=0, path=str(tmp_path / "gone.png"), name="gone.png", size=1,
        modified_time=MT_2024, md5="", added_time=time.time(),
        file_type="image", missing=1,
    )
    file_dao.insert_file(missing_record)

    target = tmp_path / "out"
    first = svc.consolidate([record, missing_record], str(target))
    assert first.linked == 1 and first.skipped == 1
    # 再次归集：目标已存在 → 跳过，不覆盖
    second = svc.consolidate([record], str(target))
    assert second.linked == 0 and second.skipped == 1


def test_consolidate_copy_fallback(env, monkeypatch):
    from src.core import consolidation as cons_mod
    file_dao, link_dao, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "big.mp4", b"video" * 100, file_type="video")

    def broken_link(src, dst):
        raise OSError("cross-volume link not permitted")

    monkeypatch.setattr(cons_mod.os, "link", broken_link)
    target = tmp_path / "out2"
    result = svc.consolidate([record], str(target))

    assert result.copied == 1 and result.linked == 0
    dest = target / "视频" / "2024" / "big.mp4"
    assert dest.read_bytes() == b"video" * 100
    # 复制件与源不是同一 inode
    assert not dest.samefile(record.path)


# ==========================================
# 修复链接
# ==========================================
def test_repair_rebuilds_missing_link(env):
    file_dao, link_dao, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "fix.jpg", b"fix")
    target = tmp_path / "out"
    svc.consolidate([record], str(target))
    dest = target / "图片" / "2024" / "fix.jpg"
    dest.unlink()
    assert not dest.exists()

    result = svc.repair_links()
    assert result.linked == 1
    assert dest.is_file() and dest.samefile(record.path)


def test_repair_drops_link_when_source_gone(env):
    file_dao, link_dao, svc, tmp_path = env
    record = _insert(file_dao, tmp_path, "lost.jpg", b"lost")
    target = tmp_path / "out"
    svc.consolidate([record], str(target))
    # 源与链接都删掉
    (target / "图片" / "2024" / "lost.jpg").unlink()
    (tmp_path / "lost.jpg").unlink()

    result = svc.repair_links()
    assert result.linked == 0
    assert link_dao.count_links() == 0   # 失效记录被清理


# ==========================================
# CSV 导出
# ==========================================
def test_export_csv(env, tmp_path):
    file_dao, _, _, _ = env
    record = _insert(file_dao, tmp_path, "r.csv-test", b"data", file_type="document")
    record.tags_str = "测试, 归档"

    out = tmp_path / "reports" / "export.csv"
    dest = export_csv([record], str(out))

    assert dest == out
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")          # UTF-8 BOM（Excel 友好）
    lines = raw.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("名称,类型")
    assert len(lines) == 2
    assert "r.csv-test" in lines[1] and "document" in lines[1]
    assert "测试, 归档" in lines[1]
