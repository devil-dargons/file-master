# === 文件路径: src/db/dao.py ===
from __future__ import annotations
import logging
from typing import Optional
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

class FileDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def _row_to_dict(self, row) -> dict:
        return dict(row) if row else None

    def insert_file(self, file_info: dict) -> int:
        sql = """INSERT OR IGNORE INTO files (path, name, size, modified_time, md5, added_time) VALUES (?, ?, ?, ?, ?, ?)"""
        params = (file_info['path'], file_info['name'], file_info['size'], file_info['modified_time'], file_info['md5'], file_info['added_time'])
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Insert file failed: {e}")
            return -1

    def insert_files_batch(self, files_info: list[dict]) -> int:
        if not files_info: return 0
        sql = """INSERT OR IGNORE INTO files (path, name, size, modified_time, md5, added_time) VALUES (?, ?, ?, ?, ?, ?)"""
        params = [(f['path'], f['name'], f['size'], f['modified_time'], f['md5'], f['added_time']) for f in files_info]
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
    # 支持多条件筛选的分页查询
    # ==========================================
    def get_files_page(self, page: int = 1, page_size: int = 50, folder_path: str = "", file_name: str = "", md5: str = "",file_type: str = "", tag_names: list = None) -> tuple[list[dict], int]:
        """
        支持多条件筛选的分页查询 (SQL 级过滤，确保总数准确)
        """
        offset = (page - 1) * page_size
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if folder_path:
            conditions.append("path LIKE ?")
            params.append(f"%{folder_path}%")
        if file_name:
            conditions.append("name LIKE ?")
            params.append(f"%{file_name}%")
        if md5:
            conditions.append("md5 = ?")
            params.append(md5)
            
        # 1. 处理文件类型 (支持输入扩展名如 'mp4' 或 '.mp4' 或 'jpg')
        if file_type:
            ft = file_type.strip().lower()
            if not ft.startswith('.'):
                ft = '.' + ft
            conditions.append("name LIKE ?")
            params.append(f"%{ft}")
            
        # 2. 处理标签 (使用 EXISTS 确保文件拥有所有指定的标签)
        if tag_names:
            for tag in tag_names:
                conditions.append("""
                    EXISTS (
                        SELECT 1 FROM file_tags ft 
                        JOIN tags t ON ft.tag_id = t.id 
                        WHERE ft.file_id = files.id AND t.tag_name LIKE ?
                    )
                """)
                params.append(f"%{tag}%")
                
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # 1. 获取符合条件的真实总数
        count_sql = f"SELECT COUNT(*) FROM files WHERE {where_clause}"
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]
        
        # 2. 获取当前页数据
        data_sql = f"SELECT * FROM files WHERE {where_clause} ORDER BY added_time DESC LIMIT ? OFFSET ?"
        data_params = params + [page_size, offset]
        
        cursor.execute(data_sql, data_params)
        data = [self._row_to_dict(row) for row in cursor.fetchall()]
        
        return data, total_count

    def get_all_files(self) -> list[dict]:
        sql = "SELECT * FROM files ORDER BY added_time DESC"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_files_by_md5(self, md5: str) -> list[dict]:
        sql = "SELECT * FROM files WHERE md5 = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (md5,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_duplicate_groups(self) -> list[dict]:
        sql = "SELECT md5, COUNT(*) as count FROM files GROUP BY md5 HAVING count > 1"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        groups = []
        for row in cursor.fetchall():
            md5 = row['md5']
            files = self.get_files_by_md5(md5)
            groups.append({"md5": md5, "count": row['count'], "files": files})
        return groups

    def update_file_path(self, old_path: str, new_path: str, new_name: str) -> bool:
        sql = "UPDATE files SET path = ?, name = ? WHERE path = ?"
        return self.db.execute_transaction(sql, (new_path, new_name, old_path))

    def update_file_info(self, file_path: str, file_info: dict) -> bool:
        sql = "UPDATE files SET size = ?, modified_time = ?, md5 = ? WHERE path = ?"
        params = (file_info['size'], file_info['modified_time'], file_info['md5'], file_path)
        return self.db.execute_transaction(sql, params)

    def delete_file_by_path(self, file_path: str) -> bool:
        sql = "DELETE FROM files WHERE path = ?"
        return self.db.execute_transaction(sql, (file_path,))
        
    def delete_files_batch(self, file_paths: list[str]) -> bool:
        if not file_paths: return True
        placeholders = ','.join(['?'] * len(file_paths))
        sql = f"DELETE FROM files WHERE path IN ({placeholders})"
        return self.db.execute_transaction(sql, tuple(file_paths))

    def get_file_by_path(self, file_path: str) -> Optional[dict]:
        sql = "SELECT * FROM files WHERE path = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (file_path,))
        row = cursor.fetchone()
        return self._row_to_dict(row)

    def update_thumbnail_path(self, file_path: str, thumb_path: str) -> bool:
        sql = "UPDATE files SET thumbnail_path = ? WHERE path = ?"
        return self.db.execute_transaction(sql, (thumb_path, file_path))

    # ==========================================
    # 新增：标签查询辅助方法 (属于 FileDAO)
    # ==========================================
    def get_tags_by_file_id(self, file_id: int) -> list[dict]:
        """获取指定文件ID关联的所有标签"""
        sql = "SELECT t.* FROM tags t JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (file_id,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_file_tags_str(self, file_id: int) -> str:
        """获取文件的标签字符串，用逗号分隔"""
        tags = self.get_tags_by_file_id(file_id)
        return ", ".join([t['tag_name'] for t in tags])


class TagDAO:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def _row_to_dict(self, row) -> dict:
        return dict(row) if row else None

    def add_tag(self, tag_name: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO tags (tag_name) VALUES (?)", (tag_name,))
            conn.commit()
            cursor.execute("SELECT id FROM tags WHERE tag_name = ?", (tag_name,))
            row = cursor.fetchone()
            return row['id'] if row else -1
        except Exception as e:
            logger.error(f"Add tag failed: {e}")
            return -1

    def get_all_tags(self) -> list[dict]:
        sql = "SELECT * FROM tags ORDER BY tag_name"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def bind_tag_to_file(self, file_id: int, tag_id: int) -> bool:
        sql = "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)"
        return self.db.execute_transaction(sql, (file_id, tag_id))

    def unbind_tag_from_file(self, file_id: int, tag_id: int) -> bool:
        sql = "DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?"
        return self.db.execute_transaction(sql, (file_id, tag_id))
        
    def get_tags_by_file_id(self, file_id: int) -> list[dict]:
        sql = "SELECT t.* FROM tags t JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ?"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (file_id,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]
        
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
        return row['value'] if row else default

    def set_setting(self, key: str, value: str):
        sql = "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
        self.db.execute_transaction(sql, (key, value))