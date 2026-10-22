"""标签 DSL golden test（开发手册 5.4）：固定语料库上断言 DSL→SQL 的行为。"""
from __future__ import annotations

import pytest

from src.core.models import FileRecord, TagGroup, TagQuery
from src.core.tag_service import DslError, build_where, parse_dsl
from src.db.dao import FileDAO, TagDAO
from src.db.database import DatabaseManager


@pytest.fixture
def corpus(temp_db, tmp_path):
    """固定语料库：f1(t1,t2) f2(t1) f3(t3) f4(无标签)。返回 (tag_ids, path->file_id)。"""
    db = DatabaseManager()
    dao = FileDAO(db)
    tag_dao = TagDAO(db)

    paths: dict[str, int] = {}
    for name in ("f1", "f2", "f3", "f4"):
        p = tmp_path / name
        p.write_text(name, encoding="utf-8")
        fid = dao.insert_file(FileRecord(
            id=0, path=str(p.resolve()), name=name, size=4, modified_time=1.0,
            md5=name, added_time=0.0, file_type="document",
        ))
        paths[name] = fid

    t1, t2, t3 = (tag_dao.add_tag(t) for t in ("a", "b", "c"))
    for fid in (paths["f1"], paths["f2"]):
        tag_dao.bind_tag_to_file(fid, t1)
    tag_dao.bind_tag_to_file(paths["f1"], t2)
    tag_dao.bind_tag_to_file(paths["f3"], t3)

    return {"tags": {"t1": t1, "t2": t2, "t3": t3}, "files": paths, "dao": dao}


def _run(dao: FileDAO, query: TagQuery) -> set[str]:
    return {rec.name for rec in dao.get_files_by_tag_query(query)}


def test_group_and_semantics(corpus):
    dao, t = corpus["dao"], corpus["tags"]
    # 组内 AND：同时拥有 t1+t2 → f1
    assert _run(dao, TagQuery(op="AND", groups=[TagGroup([t["t1"], t["t2"]])])) == {"f1"}
    # 单组单标签
    assert _run(dao, TagQuery(op="AND", groups=[TagGroup([t["t1"]])])) == {"f1", "f2"}


def test_groups_and_or_combinations(corpus):
    dao, t = corpus["dao"], corpus["tags"]
    g1, g2 = TagGroup([t["t2"]]), TagGroup([t["t3"]])
    # 分组间 OR：f1(有t2) + f3(有t3)
    assert _run(dao, TagQuery(op="OR", groups=[g1, g2])) == {"f1", "f3"}
    # 分组间 AND：无文件同时拥有 t2 与 t3
    assert _run(dao, TagQuery(op="AND", groups=[g1, g2])) == set()


def test_build_where_shape():
    where, params = build_where(TagQuery(
        op="OR", groups=[TagGroup([1, 2]), TagGroup([3])]))
    assert where == (
        "(EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id AND ft.tag_id = ?)"
        " AND EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id AND ft.tag_id = ?))"
        " OR (EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id AND ft.tag_id = ?))"
    )
    assert params == [1, 2, 3]


def test_parse_dsl_validation():
    parsed = parse_dsl({"op": "OR", "groups": [{"tagIds": [1, 1, 2]}, {"tagIds": [3]}]})
    assert parsed.op == "OR"
    assert [g.tag_ids for g in parsed.groups] == [[1, 2], [3]]  # 组内去重

    with pytest.raises(DslError):
        parse_dsl({"op": "XOR", "groups": [{"tagIds": [1]}]})
    with pytest.raises(DslError):
        parse_dsl({"op": "AND", "groups": []})
    with pytest.raises(DslError):  # 分组嵌套：深度超限
        parse_dsl({"op": "AND", "groups": [{"tagIds": [1], "groups": [{"tagIds": [2]}]}]})
    with pytest.raises(DslError):  # 组为空
        parse_dsl({"op": "AND", "groups": [{"tagIds": []}]})
    with pytest.raises(DslError):  # 标签总数 > 32
        parse_dsl({"op": "AND", "groups": [{"tagIds": list(range(1, 34))}]})
