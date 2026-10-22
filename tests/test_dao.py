# === 文件路径: tests/test_dao.py ===
"""DAO / Service 冒烟：模型返回、标签绑定与交集查询、去重分组。"""
from __future__ import annotations

import time

from src.core.file_service import FileService
from src.core.models import FileRecord, MediaMeta
from src.db.dao import FileDAO, TagDAO
from src.db.database import DatabaseManager


def _rec(path: str, name: str, md5: str) -> FileRecord:
    now = time.time()
    return FileRecord(id=0, path=path, name=name, size=100, modified_time=now,
                      md5=md5, added_time=now, file_type="document", md5_state=1)


def test_file_dao_returns_models(temp_db):
    dao = FileDAO(DatabaseManager())
    assert dao.insert_file(_rec("C:/x/a.txt", "a.txt", "m1")) > 0

    rec = dao.get_file_by_path("C:/x/a.txt")
    assert isinstance(rec, FileRecord)
    assert rec.name == "a.txt"
    assert rec.file_type == "document"

    page, total = dao.get_files_page(1, 10, file_name="a")
    assert total == 1 and page[0].path == "C:/x/a.txt"


def test_tags_flow(temp_db):
    fdao = FileDAO(DatabaseManager())
    tdao = TagDAO(DatabaseManager())

    fdao.insert_file(_rec("C:/x/a.txt", "a.txt", "m1"))
    fdao.insert_file(_rec("C:/x/b.txt", "b.txt", "m2"))

    t1 = tdao.add_tag("工作")
    t2 = tdao.add_tag("重要")
    assert t1 > 0 and t2 > 0

    a = fdao.get_file_by_path("C:/x/a.txt")
    b = fdao.get_file_by_path("C:/x/b.txt")
    assert tdao.bind_tag_to_file(a.id, t1)
    assert tdao.bind_tag_to_file(a.id, t2)
    assert tdao.bind_tag_to_file(b.id, t1)

    tags = fdao.get_tags_by_file_id(a.id)
    assert {t.tag_name for t in tags} == {"工作", "重要"}

    # 交集查询：同时拥有两个标签的只有 a.txt
    both = fdao.get_files_by_tags(["工作", "重要"])
    assert [f.path for f in both] == ["C:/x/a.txt"]

    # 分页 + 标签过滤
    page, total = fdao.get_files_page(1, 10, tag_names=["工作"])
    assert total == 2

    assert fdao.get_file_tags_str(a.id).count(",") == 1


def test_tag_empty_filter(temp_db):
    """标签“为空/不为空”是存在性判断，不依赖标签文字。"""
    fdao = FileDAO(DatabaseManager())
    tdao = TagDAO(DatabaseManager())

    a = fdao.insert_file(_rec("C:/x/a.jpg", "a.jpg", "m1"))
    b = fdao.insert_file(_rec("C:/x/b.jpg", "b.jpg", "m2"))
    fdao.insert_file(_rec("C:/x/c.jpg", "c.jpg", "m3"))

    t = tdao.add_tag("工作")
    assert tdao.bind_tag_to_file(a, t)
    assert tdao.bind_tag_to_file(b, t)

    page, total = fdao.get_files_page(1, 10, tag_mode="empty")
    assert total == 1 and [f.name for f in page] == ["c.jpg"]

    _, total = fdao.get_files_page(1, 10, tag_mode="not_empty")
    assert total == 2

    # 为空模式忽略传入的 tag_names（界面禁用输入框，仍防御性校验）
    _, total = fdao.get_files_page(1, 10, tag_names=["工作"], tag_mode="empty")
    assert total == 1


def test_aspect_not_equal_filter(temp_db):
    """宽高比“≠”：排除 1% 容差内匹配该比例的文件，无宽高元数据的文件也保留。"""
    fdao = FileDAO(DatabaseManager())

    a = fdao.insert_file(_rec("C:/x/a.jpg", "a.jpg", "m1"))
    b = fdao.insert_file(_rec("C:/x/b.jpg", "b.jpg", "m2"))
    c = fdao.insert_file(_rec("C:/x/c.jpg", "c.jpg", "m3"))

    # 630x880 与 1260x1760 都是 63:88；1000x1000 是 1:1；c 无元数据
    assert fdao.upsert_file_meta(a, MediaMeta(width=630, height=880), 0, "image")
    assert fdao.upsert_file_meta(b, MediaMeta(width=1000, height=1000), 0, "image")
    assert fdao.upsert_file_meta(c, MediaMeta(width=1260, height=1760), 0, "image")

    page, total = fdao.get_files_page(1, 10, aspect_w=63, aspect_h=88)
    assert total == 2 and {f.name for f in page} == {"a.jpg", "c.jpg"}

    page, total = fdao.get_files_page(1, 10, aspect_w=63, aspect_h=88, aspect_op="!=")
    assert total == 1 and [f.name for f in page] == ["b.jpg"]


def test_aspect_not_equal_keeps_files_without_meta(temp_db):
    """无宽高元数据的文件在“≠”查询中保留（不是 63:88）。"""
    fdao = FileDAO(DatabaseManager())
    fdao.insert_file(_rec("C:/x/no_meta.jpg", "no_meta.jpg", "m1"))
    page, total = fdao.get_files_page(1, 10, aspect_w=63, aspect_h=88, aspect_op="!=")
    assert total == 1 and [f.name for f in page] == ["no_meta.jpg"]


def test_duplicate_groups(temp_db):
    dao = FileDAO(DatabaseManager())
    dao.insert_file(_rec("C:/x/1.txt", "1.txt", "same"))
    dao.insert_file(_rec("C:/x/2.txt", "2.txt", "same"))
    dao.insert_file(_rec("C:/x/3.txt", "3.txt", "uniq"))

    groups = dao.get_duplicate_groups()
    assert len(groups) == 1
    g = groups[0]
    assert g.md5 == "same" and g.count == 2
    assert all(isinstance(f, FileRecord) for f in g.files)


def test_file_service_manage_tags(temp_db):
    fdao = FileDAO(DatabaseManager())
    tdao = TagDAO(DatabaseManager())
    fdao.insert_file(_rec("C:/x/a.txt", "a.txt", "m1"))

    service = FileService(fdao, tdao)
    res = service.manage_file_tags("C:/x/a.txt", ["新增", "工作"], [])
    assert res.success and res.success_count == 1

    tags = {t.tag_name for t in fdao.get_tags_by_file_id(1)}
    assert tags == {"新增", "工作"}

    # 移除一个
    res = service.manage_file_tags("C:/x/a.txt", [], ["新增"])
    tags = {t.tag_name for t in fdao.get_tags_by_file_id(1)}
    assert tags == {"工作"}

    # 未注册文件
    res = service.manage_file_tags("C:/nowhere.txt", ["x"], [])
    assert not res.success
