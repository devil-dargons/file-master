"""L2 元数据：图片尺寸提取、入库、幂等（mtime 未变不再重复提取）。"""
from __future__ import annotations

from PIL import Image

from src.core.meta_extractor import MetadataExtractor, extract_meta
from src.core.models import FileRecord
from src.db.dao import FileDAO
from src.db.database import DatabaseManager


def _insert_image(dao: FileDAO, path) -> int:
    stat = path.stat()
    return dao.insert_file(FileRecord(
        id=0, path=str(path.resolve()), name=path.name, size=stat.st_size,
        modified_time=stat.st_mtime, md5="0" * 32, added_time=0.0, file_type="image",
    ))


def test_extract_image_meta(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (64, 32), "red").save(path)

    meta = extract_meta(str(path), "image")
    assert meta is not None
    assert (meta.width, meta.height) == (64, 32)
    assert extract_meta(str(path), "archive") is None


def test_extractor_fills_meta_and_is_idempotent(temp_db, tmp_path):
    path = tmp_path / "b.png"
    Image.new("RGB", (32, 16), "blue").save(path)

    dao = FileDAO(DatabaseManager())
    file_id = _insert_image(dao, path)
    assert file_id > 0
    assert dao.count_pending_meta() == 1

    finished = []
    extractor = MetadataExtractor(dao, on_finished=lambda *a: finished.append(a))
    extractor.start()
    extractor.join(timeout=30)
    assert not extractor.is_alive()
    assert finished == [(1, 0)]

    meta = dao.get_file_meta(file_id)
    assert meta is not None and (meta.width, meta.height) == (32, 16)
    # mtime 未变 → 不再排队
    assert dao.count_pending_meta() == 0
