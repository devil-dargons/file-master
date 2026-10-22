# === 文件路径: src/server/lan_server.py ===
"""局域网 HTTP 服务：手机浏览器浏览图片 + 打标签。

设计要点：
- 零新依赖：标准库 ThreadingHTTPServer + BaseHTTPRequestHandler
- 认证：POST /api/login 校验主密码（VaultService.verify_password，空密码同样需确认），
  成功返回一次性随机 token（内存存储，服务重启即失效）；其余 API 需 Bearer token
- 安全：图片仅按库内 file id 提供（杜绝任意路径读取）；仅监听本机局域网
- 线程：serve_forever 跑在 daemon 线程；DAO 连接为线程局部，天然线程安全
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from src.core.file_service import FileService
from src.core.vault import VaultService
from src.db.dao import FileDAO, TagDAO
from src.db.database import DatabaseManager
from src.server.web_page import INDEX_HTML

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8765

_CONTENT_TYPES = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
    'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp', 'ico': 'image/x-icon',
}


class LanServer:
    """局域网服务门面：start/stop + 访问地址。"""

    def __init__(self, db_manager: DatabaseManager, file_service: FileService,
                 vault_service: VaultService, port: int = _DEFAULT_PORT):
        self._db = db_manager
        self._file_dao = FileDAO(db_manager)
        self._tag_dao = TagDAO(db_manager)
        self._file_service = file_service
        self._vault = vault_service
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._tokens: set[str] = set()  # 有效会话 token（内存态）

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._httpd is not None:
            return
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self._port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("LAN server started on port %d", self._port)

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._tokens.clear()
        logger.info("LAN server stopped")

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._port

    @staticmethod
    def lan_ip() -> str:
        """获取本机局域网 IP（无网时回退 127.0.0.1）。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # 不实际发包，只为选出口网卡
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            s.close()

    def access_url(self) -> str:
        return f"http://{self.lan_ip()}:{self._port}"

    # ---- HTTP handler ----
    def _make_handler(self):
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            # 静默默认的每请求日志
            def log_message(self, fmt, *args):
                logger.debug("LAN %s - %s", self.address_string(), fmt % args)

            # ---- 基础 ----
            def _send(self, code: int, body: bytes, content_type: str):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, obj, code: int = 200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _read_json(self) -> dict:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length <= 0 or length > 1 << 20:  # 上限 1MB
                        return {}
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, json.JSONDecodeError):
                    return {}

            def _authed(self) -> bool:
                auth = self.headers.get("Authorization", "")
                return auth.startswith("Bearer ") and auth[7:] in server_ref._tokens

            # ---- 路由 ----
            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/" or path == "/index.html":
                    self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if not self._authed():
                    self._send_json({"error": "unauthorized"}, 401)
                    return
                if path == "/api/tags":
                    self._send_json({"tags": [t.tag_name for t in server_ref._tag_dao.get_all_tags()]})
                elif path.startswith("/api/image/"):
                    full = parse_qs(parsed.query).get("full", [""])[0] == "1"
                    self._serve_image(self._parse_id(path, "/api/image/"), full)
                elif path.startswith("/api/file/") and path.endswith("/tags"):
                    fid = self._parse_id(path, "/api/file/", suffix="/tags")
                    self._serve_file_tags(fid)
                elif path.startswith("/api/file/"):
                    self._serve_file_info(self._parse_id(path, "/api/file/"))
                else:
                    self._send_json({"error": "not found"}, 404)

            def do_POST(self):
                path = urlparse(self.path).path
                if path == "/api/login":
                    self._handle_login()
                    return
                if not self._authed():
                    self._send_json({"error": "unauthorized"}, 401)
                    return
                if path == "/api/query":
                    self._serve_query()
                elif path.startswith("/api/file/") and path.endswith("/tags"):
                    fid = self._parse_id(path, "/api/file/", suffix="/tags")
                    self._serve_update_tags(fid)
                else:
                    self._send_json({"error": "not found"}, 404)

            @staticmethod
            def _parse_id(path: str, prefix: str, suffix: str = "") -> int | None:
                body = path[len(prefix):]
                if suffix and body.endswith(suffix):
                    body = body[:-len(suffix)]
                try:
                    return int(body)
                except ValueError:
                    return None

            # ---- 端点实现 ----
            def _handle_login(self):
                data = self._read_json()
                password = data.get("password", "")
                if not server_ref._vault.is_lock_enabled():
                    self._send_json({"ok": False, "error": "未设置主密码"}, 400)
                    return
                if server_ref._vault.verify_password(password):
                    token = secrets.token_hex(16)
                    server_ref._tokens.add(token)
                    self._send_json({"ok": True, "token": token})
                else:
                    self._send_json({"ok": False}, 403)

            def _serve_query(self):
                data = self._read_json()
                try:
                    ids = server_ref._file_dao.get_image_ids(**self._sanitize_filters(data))
                    self._send_json({"ids": ids, "total": len(ids)})
                except Exception as e:
                    logger.error("LAN query failed: %s", e)
                    self._send_json({"ids": [], "total": 0})

            @staticmethod
            def _sanitize_filters(data: dict) -> dict:
                """白名单过滤查询参数，非法值直接丢弃（防御性，DAO 层另有校验）。"""
                out: dict = {}
                if isinstance(data.get("file_name"), str):
                    out["file_name"] = data["file_name"][:200]
                if isinstance(data.get("tag_names"), list):
                    out["tag_names"] = [str(t)[:50] for t in data["tag_names"][:20]]
                for key in ("width_op", "height_op"):
                    if data.get(key) in ("=", ">", "<", ">=", "<="):
                        out[key] = data[key]
                for key in ("width_val", "height_val", "aspect_w", "aspect_h"):
                    v = data.get(key)
                    if isinstance(v, int) and 0 < v < 100000:
                        out[key] = v
                if data.get("tag_mode") in ("contains", "empty", "not_empty"):
                    out["tag_mode"] = data["tag_mode"]
                if data.get("aspect_op") in ("=", "!="):
                    out["aspect_op"] = data["aspect_op"]
                return out

            def _serve_image(self, fid: int | None, full: bool = False):
                """默认返回缩略图（不被第三方程序锁定、体积小）；full=1 返回原图。

                回退链：full → 原文件；默认 → 已有缩略图 → 即时生成 → 原文件。
                全程任意一步读取失败（如文件被独占锁定）则进入下一级，最终 500。
                """
                if fid is None:
                    self._send_json({"error": "bad id"}, 400)
                    return
                record = server_ref._file_dao.get_file_by_id(fid)
                if record is None:
                    self._send_json({"error": "not found"}, 404)
                    return

                if not full:
                    thumb = record.thumbnail_path
                    if not (thumb and os.path.exists(thumb)):
                        # 尝试即时生成（需读原文件，锁定时返回 None）
                        from src.utils.file_utils import get_video_first_frame
                        thumb = get_video_first_frame(record.path, record.md5)
                        if thumb:
                            server_ref._file_dao.update_thumbnail_path(record.path, thumb)
                    if thumb and os.path.exists(thumb):
                        try:
                            with open(thumb, "rb") as fp:
                                self._send(200, fp.read(), "image/jpeg")
                            return
                        except OSError:
                            pass  # 缩略图读失败，继续尝试原文件

                if not os.path.exists(record.path):
                    self._send_json({"error": "not found"}, 404)
                    return
                ext = record.name.rsplit(".", 1)[-1].lower() if "." in record.name else ""
                ctype = _CONTENT_TYPES.get(ext)
                if ctype is None:  # 仅允许图片类型
                    self._send_json({"error": "not an image"}, 403)
                    return
                try:
                    with open(record.path, "rb") as fp:
                        data = fp.read()
                except OSError as e:
                    logger.warning("LAN image read failed %s: %s", record.path, e)
                    self._send_json({"error": "read failed"}, 500)
                    return
                self._send(200, data, ctype)

            def _serve_file_info(self, fid: int | None):
                if fid is None:
                    self._send_json({"error": "bad id"}, 400)
                    return
                record = server_ref._file_dao.get_file_by_id(fid)
                if record is None:
                    self._send_json({"error": "not found"}, 404)
                    return
                meta = server_ref._file_dao.get_file_meta(fid)
                tags = [t.tag_name for t in server_ref._tag_dao.get_tags_by_file_id(fid)]
                self._send_json({
                    "id": record.id,
                    "name": record.name,
                    "path": record.path,
                    "size_text": _fmt_size(record.size),
                    "mtime_text": _fmt_time(record.modified_time),
                    "added_text": _fmt_time(record.added_time),
                    "md5": record.md5 or "",
                    "file_type": record.file_type,
                    "width": meta.width if meta else None,
                    "height": meta.height if meta else None,
                    "tags": tags,
                })

            def _serve_file_tags(self, fid: int | None):
                if fid is None:
                    self._send_json({"error": "bad id"}, 400)
                    return
                tags = [t.tag_name for t in server_ref._tag_dao.get_tags_by_file_id(fid)]
                self._send_json({"tags": tags})

            def _serve_update_tags(self, fid: int | None):
                if fid is None:
                    self._send_json({"ok": False, "error": "bad id"}, 400)
                    return
                record = server_ref._file_dao.get_file_by_id(fid)
                if record is None:
                    self._send_json({"ok": False, "error": "not found"}, 404)
                    return
                data = self._read_json()
                add = [str(t)[:50] for t in data.get("add", []) if str(t).strip()][:50]
                remove = [str(t)[:50] for t in data.get("remove", [])][:50]
                result = server_ref._file_service.manage_file_tags(record.path, add, remove)
                self._send_json({"ok": result.success})

        return Handler


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def _fmt_time(ts: float) -> str:
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "-"
