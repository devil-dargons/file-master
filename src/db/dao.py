# === 文件路径: src/db/dao.py ===
"""DAO 层：所有 SQL 的唯一归属。跨层返回 core.models 中的 dataclass，禁止裸 dict。"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from src.core.models import (
    AutoRule, ConsolidatedLink, DuplicateGroup, FileRecord, MediaMeta, Tag, TagQuery,
    VaultItem,
)
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


class FileDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    # ==========================================
    # 写入
    # ==========================================
    def insert_file(self, file_info: FileRecord) -> int:
        sql = (
            "INSERT OR IGNORE INTO files (path, name, size, modified_time, md5, added_time, "
            "thumbnail_path, file_type, md5_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (
            file_info.path, file_info.name, file_info.size, file_info.modified_time,
            file_info.md5, file_info.added_time, file_info.thumbnail_path,
            file_info.file_type, file_info.md5_state,
        )
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.lastrowid if cursor.lastrowid is not None else -1
        except Exception as e:
            logger.error(f"Insert file failed: {e}")
            return -1

    def insert_files_batch(self, files_info: list[FileRecord]) -> int:
        if not files_info:
            return 0
        sql = (
            "INSERT OR IGNORE INTO files (path, name, size, modified_time, md5, added_time, "
            "thumbnail_path, file_type, md5_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = [
            (f.path, f.name, f.size, f.modified_time, f.md5, f.added_time,
             f.thumbnail_path, f.file_type, f.md5_state)
            for f in files_info
        ]
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, params)
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Batch insert files failed: {e}")
            return 0

    # ==========================================
    # 多条件筛选分页查询（SQL 级过滤，总数准确）
    # ==========================================
    _IMAGE_EXTS = ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'ico')

    def _build_filter_conditions(
        self,
        folder_path: str = "",
        file_name: str = "",
        md5: str = "",
        file_type: str = "",
        tag_names: list[str] | None = None,
        include_missing: bool = True,
        width_op: str | None = None,
        width_val: int | None = None,
        height_op: str | None = None,
        height_val: int | None = None,
        aspect_w: int | None = None,
        aspect_h: int | None = None,
        tag_mode: str = "contains",
        aspect_op: str = "=",
    ) -> tuple[str, list]:
        """拼接 get_files_page / get_image_paths 共用的 WHERE 条件与参数。

        宽高筛选：width_op/height_op 取值 '=', '>', '<', '>=', '<='（白名单校验），
        通过 EXISTS 子查询关联 file_meta，不改变主查询结构。
        宽高比筛选：aspect_w:aspect_h（如 63:88），交叉相乘整数比较避免浮点误差，
        1% 相对容差匹配等比缩放图（630x880、1260x1760 均命中 63:88）。
        标签筛选：tag_mode 取 'contains'（默认，模糊匹配 tag_names）、
        'empty'（没有任何标签）、'not_empty'（有标签）；后两者忽略 tag_names。
        宽高比取反：aspect_op='!=' 时排除匹配该比例的记录（无宽高元数据的记录也算“不是”）。
        """
        conditions: list[str] = []
        params: list = []

        if folder_path:
            conditions.append("path LIKE ?")
            params.append(f"%{folder_path}%")
        if file_name:
            conditions.append("name LIKE ?")
            params.append(f"%{file_name}%")
        if md5:
            conditions.append("md5 = ?")
            params.append(md5)

        # 文件类型：支持输入扩展名如 'mp4' 或 '.mp4'
        if file_type:
            ft = file_type.strip().lower()
            if not ft.startswith('.'):
                ft = '.' + ft
            conditions.append("name LIKE ?")
            params.append(f"%{ft}")

        # 标签过滤：为空/不为空是存在性判断；否则 EXISTS 保证文件拥有所有指定标签
        tag_mode = (tag_mode or "contains").lower()
        if tag_mode == "empty":
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id)"
            )
        elif tag_mode == "not_empty":
            conditions.append(
                "EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id)"
            )
        elif tag_names:
            for tag in tag_names:
                conditions.append(
                    "EXISTS ("
                    "  SELECT 1 FROM file_tags ft"
                    "  JOIN tags t ON ft.tag_id = t.id"
                    "  WHERE ft.file_id = files.id AND t.tag_name LIKE ?"
                    ")"
                )
                params.append(f"%{tag}%")

        # 宽高筛选：EXISTS 子查询关联 file_meta（操作符白名单，参数化数值）
        _OPS = {'=', '>', '<', '>=', '<='}
        if width_op in _OPS and width_val is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM file_meta fm "
                f"WHERE fm.file_id = files.id AND fm.width {width_op} ?)"
            )
            params.append(width_val)
        if height_op in _OPS and height_val is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM file_meta fm "
                f"WHERE fm.file_id = files.id AND fm.height {height_op} ?)"
            )
            params.append(height_val)

        # 宽高比筛选：w/h ≈ aspect_w/aspect_h → |w*ah - h*aw| <= h*aw*1%
        # aspect_op='!=' 时对匹配子查询取反：不含该比例（含无宽高元数据的文件）
        if aspect_w and aspect_h:
            match_sql = (
                "EXISTS (SELECT 1 FROM file_meta fm "
                "WHERE fm.file_id = files.id AND fm.width > 0 AND fm.height > 0 "
                "AND ABS(fm.width * ? - fm.height * ?) <= fm.height * ? * 0.01)"
            )
            conditions.append(("NOT " + match_sql) if aspect_op == "!=" else match_sql)
            params.extend([aspect_h, aspect_w, aspect_w])

        if not include_missing:
            conditions.append("missing = 0")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    def get_image_paths(
        self,
        folder_path: str = "",
        file_name: str = "",
        md5: str = "",
        file_type: str = "",
        tag_names: list[str] | None = None,
        width_op: str | None = None,
        width_val: int | None = None,
        height_op: str | None = None,
        height_val: int | None = None,
        aspect_w: int | None = None,
        aspect_h: int | None = None,
        tag_mode: str = "contains",
        aspect_op: str = "=",
    ) -> list[str]:
        """按与 get_files_page 相同的过滤条件，返回全部图片路径（added_time DESC）。

        供图片查看器一次性加载完整图片序列（全局连续切换 + 标题显示真实总数）。
        排除失联文件；只 SELECT path 单列，万级数据开销可忽略。
        """
        where_clause, params = self._build_filter_conditions(
            folder_path, file_name, md5, file_type, tag_names, include_missing=False,
            width_op=width_op, width_val=width_val, height_op=height_op, height_val=height_val,
            aspect_w=aspect_w, aspect_h=aspect_h,
            tag_mode=tag_mode, aspect_op=aspect_op,
        )
        ext_conditions = " OR ".join("LOWER(name) LIKE ?" for _ in self._IMAGE_EXTS)
        where_clause += f" AND ({ext_conditions})"
        params.extend(f"%.{ext}" for ext in self._IMAGE_EXTS)

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT path FROM files WHERE {where_clause} ORDER BY added_time DESC", params)
        return [row[0] for row in cursor.fetchall()]

    def get_image_ids(self, **filters) -> list[int]:
        """与 get_image_paths 相同过滤条件，返回全部图片 id（added_time DESC）。

        供 LAN Web 服务：前端持有 id 序列做上一张/下一张/跳转浏览。
        """
        where_clause, params = self._build_filter_conditions(
            filters.get('folder_path', ''),
            filters.get('file_name', ''),
            filters.get('md5', ''),
            filters.get('file_type', ''),
            filters.get('tag_names'),
            include_missing=False,
            width_op=filters.get('width_op'), width_val=filters.get('width_val'),
            height_op=filters.get('height_op'), height_val=filters.get('height_val'),
            aspect_w=filters.get('aspect_w'), aspect_h=filters.get('aspect_h'),
            tag_mode=filters.get('tag_mode', 'contains'),
            aspect_op=filters.get('aspect_op', '='),
        )
        ext_conditions = " OR ".join("LOWER(name) LIKE ?" for _ in self._IMAGE_EXTS)
        where_clause += f" AND ({ext_conditions})"
        params.extend(f"%.{ext}" for ext in self._IMAGE_EXTS)

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT id FROM files WHERE {where_clause} ORDER BY added_time DESC", params)
        return [row[0] for row in cursor.fetchall()]

    def get_files_page(
        self,
        page: int = 1,
        page_size: int = 50,
        folder_path: str = "",
        file_name: str = "",
        md5: str = "",
        file_type: str = "",
        tag_names: list[str] | None = None,
        include_missing: bool = True,
        width_op: str | None = None,
        width_val: int | None = None,
        height_op: str | None = None,
        height_val: int | None = None,
        aspect_w: int | None = None,
        aspect_h: int | None = None,
        tag_mode: str = "contains",
        aspect_op: str = "=",
    ) -> tuple[list[FileRecord], int]:
        offset = (page - 1) * page_size
        conn = self.db.get_connection()
        cursor = conn.cursor()

        where_clause, params = self._build_filter_conditions(
            folder_path, file_name, md5, file_type, tag_names, include_missing,
            width_op=width_op, width_val=width_val, height_op=height_op, height_val=height_val,
            aspect_w=aspect_w, aspect_h=aspect_h,
            tag_mode=tag_mode, aspect_op=aspect_op,
        )

        cursor.execute(f"SELECT COUNT(*) FROM files WHERE {where_clause}", params)
        total_count = cursor.fetchone()[0]

        data_sql = f"SELECT * FROM files WHERE {where_clause} ORDER BY added_time DESC LIMIT ? OFFSET ?"
        cursor.execute(data_sql, params + [page_size, offset])
        data = [FileRecord.from_row(row) for row in cursor.fetchall()]

        return data, total_count

    def get_files_by_tags(self, tag_names: list[str]) -> list[FileRecord]:
        """多标签交集查询：文件必须同时拥有所有给定标签。"""
        if not tag_names:
            return []
        conn = self.db.get_connection()
        cursor = conn.cursor()

        conditions = []
        params: list = []
        for tag in tag_names:
            conditions.append(
                "EXISTS ("
                "  SELECT 1 FROM file_tags ft"
                "  JOIN tags t ON ft.tag_id = t.id"
                "  WHERE ft.file_id = files.id AND t.tag_name = ?"
                ")"
            )
            params.append(tag)

        where_clause = " AND ".join(conditions)
        cursor.execute(f"SELECT * FROM files WHERE {where_clause} ORDER BY added_time DESC", params)
        return [FileRecord.from_row(row) for row in cursor.fetchall()]

    def get_files_by_tag_query(self, query: TagQuery) -> list[FileRecord]:
        """组合标签查询（DSL 编译结果，开发手册 5.4）。"""
        from src.core.tag_service import DslError, build_where  # 延迟导入避免环

        if not query.groups:
            return []
        try:
            where_clause, params = build_where(query)
        except DslError:
            raise
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM files WHERE {where_clause} ORDER BY added_time DESC", params)
        return [FileRecord.from_row(row) for row in cursor.fetchall()]

    def get_all_files(self) -> list[FileRecord]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files ORDER BY added_time DESC")
        return [FileRecord.from_row(row) for row in cursor.fetchall()]

    def get_files_by_md5(self, md5: str) -> list[FileRecord]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE md5 = ?", (md5,))
        return [FileRecord.from_row(row) for row in cursor.fetchall()]

    def get_duplicate_groups(self) -> list[DuplicateGroup]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT md5, COUNT(*) as count FROM files GROUP BY md5 HAVING count > 1")
        groups: list[DuplicateGroup] = []
        for row in cursor.fetchall():
            groups.append(DuplicateGroup(md5=row["md5"], files=self.get_files_by_md5(row["md5"])))
        return groups

    def get_path_cache(self) -> dict[str, FileRecord]:
        """扫描增量判重缓存：path -> 已有记录（size/mtime/md5）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT path, size, modified_time, md5, missing FROM files")
            return {row["path"]: FileRecord.from_row(row) for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to load path cache: {e}")
            return {}

    # ==========================================
    # 更新 / 删除
    # ==========================================
    def update_file_path(self, old_path: str, new_path: str, new_name: str) -> bool:
        sql = "UPDATE files SET path = ?, name = ? WHERE path = ?"
        return self.db.execute_transaction(sql, (new_path, new_name, old_path))

    def update_file_info(self, file_path: str, file_info: FileRecord) -> bool:
        sql = ("UPDATE files SET size = ?, modified_time = ?, md5 = ?, file_type = ?, "
               "md5_state = ?, missing = 0 WHERE path = ?")
        params = (file_info.size, file_info.modified_time, file_info.md5,
                  file_info.file_type, file_info.md5_state, file_path)
        return self.db.execute_transaction(sql, params)

    def set_missing(self, file_path: str, missing: int) -> bool:
        sql = "UPDATE files SET missing = ? WHERE path = ?"
        return self.db.execute_transaction(sql, (missing, file_path))

    def mark_missing(self, roots: list[str], seen_paths: set[str]) -> int:
        """扫描结束后失联判定：roots 下未见到的记录标记 missing=1，重新出现的恢复为 0。

        只在整棵目录扫描完成时调用（扫描被中断不判定，避免误标）。
        返回本次新标记为失联的记录数。
        """
        if not roots:
            return 0
        prefixes = [os.path.normcase(os.path.normpath(os.path.abspath(r))) for r in roots]
        seen = {os.path.normcase(os.path.normpath(p)) for p in seen_paths}
        conn = self.db.get_connection()
        new_missing = 0
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, path, missing FROM files")
            updates: list[tuple[int, int]] = []
            for row in cursor.fetchall():
                norm = os.path.normcase(os.path.normpath(row["path"]))
                if not any(norm == p or norm.startswith(p + os.sep) for p in prefixes):
                    continue
                want = 0 if norm in seen else 1
                if want != (row["missing"] or 0):
                    updates.append((want, row["id"]))
                    if want == 1:
                        new_missing += 1
            if updates:
                cursor.executemany("UPDATE files SET missing = ? WHERE id = ?", updates)
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Mark missing failed: {e}")
            return 0
        return new_missing

    def count_missing(self) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM files WHERE missing = 1")
        return cursor.fetchone()[0]

    def clear_missing(self) -> int:
        """清理失联索引记录（不触碰磁盘文件）。返回删除条数。"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files WHERE missing = 1")
            count = cursor.rowcount
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            logger.error(f"Clear missing failed: {e}")
            return 0

    def delete_file_by_path(self, file_path: str) -> bool:
        sql = "DELETE FROM files WHERE path = ?"
        return self.db.execute_transaction(sql, (file_path,))

    def delete_files_batch(self, file_paths: list[str]) -> bool:
        if not file_paths:
            return True
        placeholders = ','.join(['?'] * len(file_paths))
        sql = f"DELETE FROM files WHERE path IN ({placeholders})"
        return self.db.execute_transaction(sql, tuple(file_paths))

    def get_file_by_path(self, file_path: str) -> Optional[FileRecord]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE path = ?", (file_path,))
        row = cursor.fetchone()
        return FileRecord.from_row(row) if row else None

    def get_file_by_id(self, file_id: int) -> Optional[FileRecord]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        return FileRecord.from_row(row) if row else None

    def update_thumbnail_path(self, file_path: str, thumb_path: str) -> bool:
        sql = "UPDATE files SET thumbnail_path = ? WHERE path = ?"
        return self.db.execute_transaction(sql, (thumb_path, file_path))

    def get_records_by_paths(self, paths: list[str]) -> list[FileRecord]:
        """按路径批量取记录（分批 IN 查询，供规则引擎对新增文件打标）。"""
        if not paths:
            return []
        conn = self.db.get_connection()
        cursor = conn.cursor()
        result: list[FileRecord] = []
        try:
            for start in range(0, len(paths), 500):
                chunk = paths[start:start + 500]
                placeholders = ",".join(["?"] * len(chunk))
                cursor.execute(f"SELECT * FROM files WHERE path IN ({placeholders})", chunk)
                result.extend(FileRecord.from_row(row) for row in cursor.fetchall())
        except Exception as e:
            logger.error(f"Get records by paths failed: {e}")
        return result

    # ==========================================
    # 元数据（file_meta）
    # ==========================================
    def get_files_pending_meta(self) -> list[FileRecord]:
        """待提取元数据的文件：无记录，或文件 mtime 与提取时不一致。"""
        sql = (
            "SELECT f.* FROM files f LEFT JOIN file_meta m ON m.file_id = f.id "
            "WHERE f.missing = 0 AND f.file_type IN ('image', 'video', 'audio', 'document') "
            "AND (m.file_id IS NULL "
            "     OR json_extract(m.extra_json, '$.mtime') IS NOT f.modified_time)"
        )
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            return [FileRecord.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Query pending meta failed: {e}")
            return []

    def count_pending_meta(self) -> int:
        sql = (
            "SELECT COUNT(*) FROM files f LEFT JOIN file_meta m ON m.file_id = f.id "
            "WHERE f.missing = 0 AND f.file_type IN ('image', 'video', 'audio', 'document') "
            "AND (m.file_id IS NULL "
            "     OR json_extract(m.extra_json, '$.mtime') IS NOT f.modified_time)"
        )
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchone()[0]

    def upsert_file_meta(self, file_id: int, meta: MediaMeta,
                         src_mtime: float, file_type: str) -> bool:
        sql = (
            "INSERT INTO file_meta "
            "(file_id, width, height, duration_sec, page_count, shot_time, camera, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(file_id) DO UPDATE SET width = excluded.width, height = excluded.height, "
            "duration_sec = excluded.duration_sec, page_count = excluded.page_count, "
            "shot_time = excluded.shot_time, camera = excluded.camera, extra_json = excluded.extra_json"
        )
        extra = json.dumps({"mtime": src_mtime, "type": file_type}, ensure_ascii=False)
        params = (file_id, meta.width, meta.height, meta.duration_sec,
                  meta.page_count, meta.shot_time, meta.camera, extra)
        return self.db.execute_transaction(sql, params)

    def get_file_meta(self, file_id: int) -> MediaMeta | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM file_meta WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        return MediaMeta.from_row(row) if row else None

    def update_file_type(self, path: str, file_type: str) -> bool:
        """轻量修正 file_type（扫描自愈用，不触碰 size/mtime/md5）。"""
        return self.db.execute_transaction(
            "UPDATE files SET file_type = ? WHERE path = ?", (file_type, path))

    # ==========================================
    # 标签辅助
    # ==========================================
    def get_tags_by_file_id(self, file_id: int) -> list[Tag]:
        sql = "SELECT t.* FROM tags t JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (file_id,))
        return [Tag.from_row(row) for row in cursor.fetchall()]

    def get_file_tags_str(self, file_id: int) -> str:
        tags = self.get_tags_by_file_id(file_id)
        return ", ".join(t.tag_name for t in tags)


class TagDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add_tag(self, tag_name: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO tags (tag_name) VALUES (?)", (tag_name,))
            conn.commit()
            cursor.execute("SELECT id FROM tags WHERE tag_name = ?", (tag_name,))
            row = cursor.fetchone()
            return row["id"] if row else -1
        except Exception as e:
            logger.error(f"Add tag failed: {e}")
            return -1

    def get_all_tags(self) -> list[Tag]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tags ORDER BY tag_name")
        return [Tag.from_row(row) for row in cursor.fetchall()]

    def bind_tag_to_file(self, file_id: int, tag_id: int, source: str = "manual") -> bool:
        sql = "INSERT OR IGNORE INTO file_tags (file_id, tag_id, source) VALUES (?, ?, ?)"
        return self.db.execute_transaction(sql, (file_id, tag_id, source))

    def bind_tags_bulk(self, rows: list[tuple[int, int, str]]) -> int:
        """批量绑定（file_id, tag_id, source）；已存在的绑定保持原 source。"""
        if not rows:
            return 0
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id, source) VALUES (?, ?, ?)", rows)
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"Bulk bind tags failed: {e}")
            return 0

    def clear_auto_tags(self) -> int:
        """删除全部自动标签绑定（source='auto'），手动绑定不受影响。"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_tags WHERE source = 'auto'")
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"Clear auto tags failed: {e}")
            return 0

    def set_tag_auto(self, tag_id: int, is_auto: int = 1) -> bool:
        sql = "UPDATE tags SET is_auto = ? WHERE id = ?"
        return self.db.execute_transaction(sql, (is_auto, tag_id))

    def unbind_tag_from_file(self, file_id: int, tag_id: int) -> bool:
        sql = "DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?"
        return self.db.execute_transaction(sql, (file_id, tag_id))

    def get_tags_by_file_id(self, file_id: int) -> list[Tag]:
        sql = "SELECT t.* FROM tags t JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (file_id,))
        return [Tag.from_row(row) for row in cursor.fetchall()]

    def delete_tag(self, tag_id: int) -> bool:
        sql = "DELETE FROM tags WHERE id = ?"
        return self.db.execute_transaction(sql, (tag_id,))


class SettingsDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_setting(self, key: str, default: str = "") -> str:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        sql = "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
        self.db.execute_transaction(sql, (key, value))


class AutoRuleDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add_rule(self, name: str, match_kind: str, pattern: str, tag_id: int,
                 enabled: int = 1) -> int:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO auto_rules (name, match_kind, pattern, tag_id, enabled) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, match_kind, pattern, tag_id, enabled),
            )
            conn.commit()
            return cursor.lastrowid if cursor.lastrowid is not None else -1
        except Exception as e:
            conn.rollback()
            logger.error(f"Add auto rule failed: {e}")
            return -1

    def get_all_rules(self) -> list[AutoRule]:
        sql = (
            "SELECT r.*, t.tag_name FROM auto_rules r "
            "LEFT JOIN tags t ON t.id = r.tag_id ORDER BY r.id"
        )
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            return [AutoRule.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Get auto rules failed: {e}")
            return []

    def delete_rule(self, rule_id: int) -> bool:
        sql = "DELETE FROM auto_rules WHERE id = ?"
        return self.db.execute_transaction(sql, (rule_id,))

    def set_rule_enabled(self, rule_id: int, enabled: int) -> bool:
        sql = "UPDATE auto_rules SET enabled = ? WHERE id = ?"
        return self.db.execute_transaction(sql, (enabled, rule_id))


class VaultDAO:
    """vault_items 表读写（M4 加密区）。"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add_item(self, original_path: str, enc_path: str, enc_size: int, orig_size: int,
                 wrapped_dek: bytes, nonce: bytes) -> int:
        sql = (
            "INSERT INTO vault_items (original_path, enc_path, enc_size, orig_size, "
            "wrapped_dek, nonce, added_time) VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (original_path, enc_path, enc_size, orig_size,
                                 wrapped_dek, nonce, time.time()))
            conn.commit()
            return cursor.lastrowid if cursor.lastrowid is not None else -1
        except Exception as e:
            conn.rollback()
            logger.error(f"Add vault item failed: {e}")
            return -1

    def get_item(self, item_id: int) -> VaultItem | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vault_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return VaultItem.from_row(row) if row else None

    def list_items(self) -> list[VaultItem]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vault_items ORDER BY added_time DESC, id DESC")
        return [VaultItem.from_row(row) for row in cursor.fetchall()]

    def delete_item(self, item_id: int) -> bool:
        sql = "DELETE FROM vault_items WHERE id = ?"
        return self.db.execute_transaction(sql, (item_id,))

    def update_wrapped_dek(self, item_id: int, wrapped_dek: bytes) -> bool:
        sql = "UPDATE vault_items SET wrapped_dek = ? WHERE id = ?"
        return self.db.execute_transaction(sql, (wrapped_dek, item_id))

    def count_items(self) -> tuple[int, int]:
        """返回（条目数，密文总字节数）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS n, COALESCE(SUM(enc_size), 0) AS total FROM vault_items")
        row = cursor.fetchone()
        return int(row["n"]), int(row["total"])


class ConsolidatedLinkDAO:
    """consolidated_links 表读写（M5 归集区）。"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add_link(self, file_id: int, link_path: str) -> int:
        sql = "INSERT OR IGNORE INTO consolidated_links (file_id, link_path, created_time) VALUES (?, ?, ?)"
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (file_id, link_path, time.time()))
            conn.commit()
            return cursor.lastrowid if cursor.lastrowid is not None else -1
        except Exception as e:
            conn.rollback()
            logger.error(f"Add consolidated link failed: {e}")
            return -1

    def get_link_by_path(self, link_path: str) -> ConsolidatedLink | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM consolidated_links WHERE link_path = ?", (link_path,))
        row = cursor.fetchone()
        return ConsolidatedLink.from_row(row) if row else None

    def list_links(self) -> list[ConsolidatedLink]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM consolidated_links ORDER BY id")
        return [ConsolidatedLink.from_row(row) for row in cursor.fetchall()]

    def count_links(self) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM consolidated_links")
        return int(cursor.fetchone()[0])

    def delete_link(self, link_id: int) -> bool:
        return self.db.execute_transaction("DELETE FROM consolidated_links WHERE id = ?", (link_id,))

    def delete_links_for_file(self, file_id: int) -> bool:
        return self.db.execute_transaction(
            "DELETE FROM consolidated_links WHERE file_id = ?", (file_id,))
