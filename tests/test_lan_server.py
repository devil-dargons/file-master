# === 文件路径: tests/test_lan_server.py ===
"""LAN 服务端到端测试：临时库 + 真实 HTTP 请求。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from PIL import Image

from src.core.file_service import FileService
from src.core.vault import VaultService
from src.db.dao import FileDAO, SettingsDAO, TagDAO, VaultDAO
from src.db.database import DatabaseManager
from src.server.lan_server import LanServer


@pytest.fixture
def lan_env(temp_db, tmp_path):
    db = DatabaseManager()
    # 造 3 张真实图片 + 元数据
    sizes = [(630, 880), (1920, 1080), (800, 600)]
    conn = db.get_connection()
    for i, (w, h) in enumerate(sizes):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (w, h), (i * 80, 100, 200)).save(p)
        conn.execute(
            "INSERT INTO files (path, name, size, modified_time, md5, added_time, file_type)"
            " VALUES (?,?,?,?,?,?,?)",
            (str(p), p.name, p.stat().st_size, 1700000000.0, "md5x", 1700000000.0 + i, "image"))
        fid = conn.execute("SELECT id FROM files WHERE path=?", (str(p),)).fetchone()[0]
        conn.execute("INSERT INTO file_meta (file_id, width, height) VALUES (?,?,?)", (fid, w, h))
    conn.execute("INSERT OR IGNORE INTO tags (tag_name) VALUES ('t1'),('t2')")
    conn.commit()

    file_dao = FileDAO(db)
    tag_dao = TagDAO(db)
    fs = FileService(file_dao, tag_dao)
    vault = VaultService(db, SettingsDAO(db), VaultDAO(db), tmp_path / "vault")
    vault.set_master_password("")  # 空密码：仍需登录确认

    server = LanServer(db, fs, vault, port=0)
    server.start()
    port = server._httpd.server_address[1]
    yield server, f"http://127.0.0.1:{port}", fs, tag_dao
    server.stop()


def _req(base, path, data=None, token=None):
    r = urllib.request.Request(base + path)
    if data is not None:
        r.data = json.dumps(data).encode()
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(r)


def _login(base, password=""):
    return json.loads(_login_raw(base, password).read())


def _login_raw(base, password=""):
    return _req(base, "/api/login", {"password": password})


class TestLanServer:
    def test_index_page_served(self, lan_env):
        _, base, _, _ = lan_env
        html = _req(base, "/").read().decode()
        assert "FileMaster LAN" in html
        assert "drawer-filter" in html and "drawer-tags" in html and "drawer-detail" in html

    def test_unauthorized_blocked(self, lan_env):
        _, base, _, _ = lan_env
        with pytest.raises(urllib.error.HTTPError) as e:
            _req(base, "/api/query", {})
        assert e.value.code == 401

    def test_wrong_password_rejected(self, lan_env):
        _, base, _, _ = lan_env
        with pytest.raises(urllib.error.HTTPError) as e:
            _login_raw(base, "wrong")
        assert e.value.code == 403

    def test_empty_password_login_required_but_passes(self, lan_env):
        """空密码也必须走 /api/login 拿 token，不能直接访问。"""
        _, base, _, _ = lan_env
        with pytest.raises(urllib.error.HTTPError):
            _req(base, "/api/query", {})  # 无 token 仍被拒
        d = _login(base, "")
        assert d["ok"] and d["token"]

    def test_query_and_filters(self, lan_env):
        _, base, _, _ = lan_env
        token = _login(base)["token"]
        d = json.loads(_req(base, "/api/query", {}, token).read())
        assert d["total"] == 3
        d = json.loads(_req(base, "/api/query", {"aspect_w": 63, "aspect_h": 88}, token).read())
        assert d["total"] == 1
        d = json.loads(_req(base, "/api/query", {"width_op": ">", "width_val": 1000}, token).read())
        assert d["total"] == 1

    def test_image_serving_and_type_guard(self, lan_env):
        _, base, _, _ = lan_env
        token = _login(base)["token"]
        ids = json.loads(_req(base, "/api/query", {}, token).read())["ids"]
        # 无缩略图时：即时生成并返回 JPEG
        body = _req(base, f"/api/image/{ids[0]}", token=token).read()
        assert body[:3] == b"\xff\xd8\xff"  # JPEG SOI
        # full=1 返回原图
        body_full = _req(base, f"/api/image/{ids[0]}?full=1", token=token).read()
        assert body_full[:3] == b"\xff\xd8\xff"

    def test_image_prefers_existing_thumbnail(self, lan_env):
        server, base, _, _ = lan_env
        token = _login(base)["token"]
        ids = json.loads(_req(base, "/api/query", {}, token).read())["ids"]
        # 第一次请求后缩略图已生成并入库
        _req(base, f"/api/image/{ids[0]}", token=token).read()
        record = server._file_dao.get_file_by_id(ids[0])
        assert record.thumbnail_path and record.thumbnail_path.endswith(".jpg")

    def test_file_info_and_tags(self, lan_env):
        _, base, _, _ = lan_env
        token = _login(base)["token"]
        ids = json.loads(_req(base, "/api/query", {}, token).read())["ids"]
        info = json.loads(_req(base, f"/api/file/{ids[0]}", token=token).read())
        assert info["width"] in (630, 1920, 800)
        assert info["name"].startswith("p")

        d = json.loads(_req(base, f"/api/file/{ids[0]}/tags",
                            {"add": ["t1", "新标签"], "remove": []}, token).read())
        assert d["ok"]
        tags = json.loads(_req(base, f"/api/file/{ids[0]}/tags", token=token).read())["tags"]
        assert set(tags) == {"t1", "新标签"}

    def test_stop_clears_tokens(self, lan_env):
        server, base, _, _ = lan_env
        token = _login(base)["token"]
        server.stop()
        assert not server.is_running
        assert not server._tokens
