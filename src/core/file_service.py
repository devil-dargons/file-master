from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path
from typing import Optional

try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False
    logging.warning("send2trash not installed. Delete operations will use physical removal.")

from src.db.dao import FileDAO, TagDAO
from src.core.signals import AppSignals

logger = logging.getLogger(__name__)

# 冲突处理策略常量
STRATEGY_OVERWRITE = "overwrite"
STRATEGY_SKIP = "skip"
STRATEGY_RENAME = "rename"

class FileService:
    """
    统一文件操作总线
    封装所有对物理文件和数据库记录的修改操作，确保状态一致性。
    """
    def __init__(self, file_dao: FileDAO, tag_dao: TagDAO):
        self.file_dao = file_dao
        self.tag_dao = tag_dao
        self.signals = AppSignals()

    def _get_unique_path(self, target_path: Path) -> Path:
        """如果目标路径已存在，自动在文件名后追加 _1, _2 等序号"""
        if not target_path.exists():
            return target_path
        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent
        counter = 1
        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return new_path
            counter += 1

    def _build_result(self, success_count: int, fail_count: int, errors: list[str]) -> dict:
        """统一构建返回结果"""
        is_success = fail_count == 0
        msg = f"成功处理 {success_count} 个文件。"
        if fail_count > 0:
            msg += f" 失败 {fail_count} 个。"
        return {
            "success": is_success,
            "message": msg,
            "data": {
                "success_count": success_count,
                "fail_count": fail_count,
                "errors": errors
            }
        }

    # ==========================================
    # 1. 重命名操作
    # ==========================================
    def rename_file(self, old_path: str, new_name: str) -> dict:
        """重命名单个文件"""
        errors = []
        old_p = Path(old_path)
        new_p = old_p.parent / new_name
        
        if not old_p.exists():
            return self._build_result(0, 1, ["原文件不存在"])
            
        if new_p.exists() and str(old_p) != str(new_p):
            return self._build_result(0, 1, ["目标文件名已存在"])

        try:
            # 1. 物理重命名
            old_p.rename(new_p)
            
            # 2. 数据库更新
            db_success = self.file_dao.update_file_path(str(old_p), str(new_p), new_name)
            if not db_success:
                logger.error(f"DB sync failed after rename: {old_p} -> {new_p}")
                errors.append("物理重命名成功，但数据库同步失败，请重新扫描！")
                self.signals.file_operation_result.emit("rename", False, "数据库同步失败")
            else:
                self.signals.file_operation_result.emit("rename", True, "重命名成功")
                self.signals.data_changed.emit()
                
            return self._build_result(1, 0, errors)
        except Exception as e:
            logger.error(f"Rename failed: {e}")
            return self._build_result(0, 1, [str(e)])

    # ==========================================
    # 2. 移动与复制操作
    # ==========================================
    def move_files(self, source_paths: list[str], target_dir: str, conflict_strategy: str = STRATEGY_SKIP) -> dict:
        return self._transfer_files(source_paths, target_dir, is_move=True, conflict_strategy=conflict_strategy)

    def copy_files(self, source_paths: list[str], target_dir: str, conflict_strategy: str = STRATEGY_SKIP) -> dict:
        return self._transfer_files(source_paths, target_dir, is_move=False, conflict_strategy=conflict_strategy)

    def _transfer_files(self, source_paths: list[str], target_dir: str, is_move: bool, conflict_strategy: str) -> dict:
        """底层移动/复制逻辑"""
        success_count = 0
        fail_count = 0
        errors = []
        op_type = "move" if is_move else "copy"
        target_dir_p = Path(target_dir)
        os.makedirs(target_dir_p, exist_ok=True)

        for src_path_str in source_paths:
            src_p = Path(src_path_str)
            if not src_p.exists():
                fail_count += 1
                errors.append(f"源文件不存在: {src_p}")
                continue

            dst_p = target_dir_p / src_p.name
            
            # 冲突处理
            if dst_p.exists():
                if conflict_strategy == STRATEGY_SKIP:
                    continue
                elif conflict_strategy == STRATEGY_RENAME:
                    dst_p = self._get_unique_path(dst_p)
                elif conflict_strategy == STRATEGY_OVERWRITE:
                    try:
                        dst_p.unlink() # 删除目标文件以允许覆盖
                    except Exception as e:
                        fail_count += 1
                        errors.append(f"无法覆盖 {dst_p}: {e}")
                        continue

            try:
                # 1. 物理操作
                if is_move:
                    shutil.move(str(src_p), str(dst_p))
                else:
                    shutil.copy2(str(src_p), str(dst_p)) # copy2 保留元数据

                # 2. 数据库操作
                if is_move:
                    # 移动：更新数据库中的路径
                    db_ok = self.file_dao.update_file_path(str(src_p), str(dst_p), dst_p.name)
                    if not db_ok:
                        errors.append(f"移动成功但DB同步失败: {src_p}")
                else:
                    # 复制：如果是全新路径，可选择是否插入新记录（这里默认不自动插入，保持数据库记录的是原始扫描文件）
                    # 若需入库，可在此调用 file_dao.insert_file，但需要重新计算MD5，为保持性能暂不自动入库。
                    pass

                success_count += 1
            except Exception as e:
                fail_count += 1
                errors.append(f"{op_type} 失败 {src_p}: {e}")

        if success_count > 0:
            self.signals.data_changed.emit()
        self.signals.file_operation_result.emit(op_type, fail_count == 0, f"成功{success_count}, 失败{fail_count}")
        
        return self._build_result(success_count, fail_count, errors)

    # ==========================================
    # 3. 删除操作 (集成回收站)
    # ==========================================
    def delete_files(self, file_paths: list[str], use_trash: bool = True) -> dict:
        """删除文件。优先使用 send2trash 移入回收站"""
        success_count = 0
        fail_count = 0
        errors = []

        for path_str in file_paths:
            p = Path(path_str)
            if not p.exists():
                # 如果物理文件已不存在，但数据库有记录，也允许清理数据库
                self.file_dao.delete_file_by_path(path_str)
                success_count += 1
                continue

            try:
                # 1. 物理删除/移入回收站
                if use_trash and HAS_SEND2TRASH:
                    send2trash(str(p))
                else:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                
                # 2. 数据库删除
                self.file_dao.delete_file_by_path(path_str)
                success_count += 1
            except Exception as e:
                fail_count += 1
                errors.append(f"删除失败 {p}: {e}")

        if success_count > 0:
            self.signals.data_changed.emit()
        self.signals.file_operation_result.emit("delete", fail_count == 0, f"成功{success_count}, 失败{fail_count}")
        
        return self._build_result(success_count, fail_count, errors)

    # ==========================================
    # 4. 标签管理操作
    # ==========================================
    def manage_file_tags(self, file_path: str, tags_to_add: list[str], tags_to_remove: list[str]) -> dict:
        """为指定文件添加或移除标签"""
        file_info = self.file_dao.get_file_by_path(file_path)
        if not file_info:
            return self._build_result(0, 1, ["文件未在数据库中注册"])
            
        file_id = file_info['id']
        errors = []

        try:
            # 添加标签
            for tag_name in tags_to_add:
                tag_name = tag_name.strip()
                if not tag_name: continue
                tag_id = self.tag_dao.add_tag(tag_name) # 幂等操作
                if tag_id != -1:
                    self.tag_dao.bind_tag_to_file(file_id, tag_id)
                    
            # 移除标签
            all_tags = self.tag_dao.get_all_tags()
            tag_map = {t['tag_name']: t['id'] for t in all_tags}
            
            for tag_name in tags_to_remove:
                tag_name = tag_name.strip()
                if tag_name in tag_map:
                    self.tag_dao.unbind_tag_from_file(file_id, tag_map[tag_name])
                    
            self.signals.data_changed.emit()
            return self._build_result(1, 0, [])
        except Exception as e:
            logger.error(f"Manage tags failed: {e}")
            return self._build_result(0, 1, [str(e)])