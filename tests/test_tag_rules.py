"""自动标签规则：匹配判定、按路径应用、全量重建（手动标签保留）、扫描联动。"""
from __future__ import annotations

from src.core.models import AutoRule, FileRecord
from src.core.scanner import FileScanner
from src.core.tag_service import TagRuleEngine, match_rule
from src.db.dao import AutoRuleDAO, FileDAO, TagDAO
from src.db.database import DatabaseManager


def _make_rule(tag_dao: TagDAO, rule_dao: AutoRuleDAO, name: str,
               kind: str, pattern: str, tag: str, enabled: int = 1) -> None:
    tag_id = tag_dao.add_tag(tag)
    assert tag_id > 0
    rule_dao.add_rule(name, kind, pattern, tag_id, enabled)


def _bindings(file_id: int) -> dict[str, str]:
    conn = DatabaseManager().get_connection()
    rows = conn.execute(
        "SELECT t.tag_name, ft.source FROM file_tags ft "
        "JOIN tags t ON t.id = ft.tag_id WHERE ft.file_id = ?",
        (file_id,),
    ).fetchall()
    return {row["tag_name"]: row["source"] for row in rows}


def _insert(dao: FileDAO, path, file_type: str = "other") -> int:
    stat = path.stat()
    file_id = dao.insert_file(FileRecord(
        id=0, path=str(path.resolve()), name=path.name, size=stat.st_size,
        modified_time=stat.st_mtime, md5="1" * 32, added_time=0.0, file_type=file_type,
    ))
    assert file_id > 0
    return file_id


def test_match_rule_ext_and_dir():
    ext = AutoRule(id=0, name="e", match_kind="ext", pattern="jpg, png", tag_id=1)
    directory = AutoRule(id=0, name="d", match_kind="dir", pattern="Shots", tag_id=1)

    assert match_rule(ext, "D:/pics/a.JPG")
    assert match_rule(ext, "b.png")
    assert not match_rule(ext, "c.gif")
    assert match_rule(directory, "d:/pics/shots/x.jpg")
    assert not match_rule(directory, "d:/pics/misc/x.jpg")


def test_apply_and_rebuild_keeps_manual(temp_db, tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"fake")
    txt = tmp_path / "b.txt"
    txt.write_text("x", encoding="utf-8")

    db = DatabaseManager()
    file_dao = FileDAO(db)
    tag_dao = TagDAO(db)
    rule_dao = AutoRuleDAO(db)
    _make_rule(tag_dao, rule_dao, "图片", "ext", "jpg png", "photo")
    _make_rule(tag_dao, rule_dao, "停用规则", "dir", "never", "hidden", enabled=0)

    engine = TagRuleEngine(db)
    fid_img = _insert(file_dao, img, file_type="image")
    fid_txt = _insert(file_dao, txt, file_type="document")

    applied = engine.apply_to_paths([str(img.resolve()), str(txt.resolve())])
    assert applied == 1
    assert _bindings(fid_img) == {"photo": "auto"}
    assert _bindings(fid_txt) == {}

    # 手动标签在重建后保留，自动标签重算
    manual_tag = tag_dao.add_tag("my_manual")
    tag_dao.bind_tag_to_file(fid_txt, manual_tag, source="manual")
    engine.rebuild_all()
    assert _bindings(fid_img) == {"photo": "auto"}
    assert _bindings(fid_txt) == {"my_manual": "manual"}


def test_scanner_applies_rules_to_new_files(temp_db, tmp_path):
    src = tmp_path / "shots"
    src.mkdir()
    (src / "a.txt").write_text("shot", encoding="utf-8")
    other = tmp_path / "misc"
    other.mkdir()
    (other / "b.txt").write_text("misc", encoding="utf-8")

    db = DatabaseManager()
    _make_rule(TagDAO(db), AutoRuleDAO(db), "截图", "dir", "shots", "screenshot")

    results = []
    scanner = FileScanner([str(tmp_path)], is_incremental=True, on_finished=lambda *a: results.append(a))
    scanner.start()
    scanner.join(timeout=60)
    assert results == [(2, 0)]

    file_dao = FileDAO(db)
    fid_a = file_dao.get_file_by_path(str((src / "a.txt").resolve())).id
    fid_b = file_dao.get_file_by_path(str((other / "b.txt").resolve())).id
    assert _bindings(fid_a) == {"screenshot": "auto"}
    assert _bindings(fid_b) == {}
