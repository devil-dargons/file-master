# === 文件路径: src/core/tag_service.py ===
"""标签规则引擎：auto_rules 表驱动的目录/扩展名自动打标（开发手册 5.3 L1）。

- match_kind='ext'：pattern 为逗号/分号/空格分隔的扩展名（可带点），大小写不敏感
- match_kind='dir'：pattern 为路径片段，大小写不敏感的包含匹配
- 自动标签以 file_tags.source='auto' 写入；已存在的绑定保持原 source（手动优先）
- 规则停用/删除不回溯清理；由「重建自动标签」全量重算
"""
from __future__ import annotations

import logging
import os
import re

from src.core.models import AutoRule, FileRecord, TagGroup, TagQuery
from src.db.dao import AutoRuleDAO, FileDAO, TagDAO
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

_SPLIT_RE = re.compile(r"[,;\s]+")
_EXT_CACHE: dict[str, frozenset[str]] = {}

# ---- 标签 DSL（开发手册 5.4）----
MAX_DSL_DEPTH = 3   # 顶层 op + 分组，不允许分组内再嵌套（深度上限 3 由扁平结构保证）
MAX_DSL_TAGS = 32


class DslError(ValueError):
    """DSL 结构非法。"""


def parse_dsl(payload: dict) -> TagQuery:
    """解析并校验 DSL JSON（深度 ≤3、标签总数 ≤32、组非空）。"""
    if not isinstance(payload, dict):
        raise DslError("DSL 必须是 JSON 对象")
    op = payload.get("op")
    if op not in ("AND", "OR"):
        raise DslError("op 必须是 'AND' 或 'OR'")
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        raise DslError("至少需要一个条件分组")

    parsed: list[TagGroup] = []
    total_tags = 0
    for group in groups:
        if not isinstance(group, dict) or "groups" in group:
            raise DslError(f"分组不支持嵌套（深度上限 {MAX_DSL_DEPTH}）")
        ids = group.get("tagIds")
        if (not isinstance(ids, list) or not ids
                or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids)):
            raise DslError("每组必须包含非空的 tagIds（正整数数组）")
        total_tags += len(ids)
        parsed.append(TagGroup(tag_ids=list(dict.fromkeys(ids))))
    if total_tags > MAX_DSL_TAGS:
        raise DslError(f"标签总数超过上限 {MAX_DSL_TAGS}")
    return TagQuery(op=op, groups=parsed)


def _group_clause(group: TagGroup) -> str:
    """组内 AND：每个标签一个 EXISTS 子查询。"""
    return " AND ".join(
        "EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = files.id AND ft.tag_id = ?)"
        for _ in group.tag_ids
    )


def build_where(query: TagQuery) -> tuple[str, list[int]]:
    """编译 TagQuery → (WHERE 片段, 参数列表)；最终 SQL 由 DAO 组装。"""
    clauses: list[str] = []
    params: list[int] = []
    for group in query.groups:
        clauses.append(f"({_group_clause(group)})")
        params.extend(group.tag_ids)
    joiner = f" {query.op} "
    return joiner.join(clauses), params


def _ext_set(pattern: str) -> frozenset[str]:
    cached = _EXT_CACHE.get(pattern)
    if cached is None:
        exts: set[str] = set()
        for token in _SPLIT_RE.split(pattern.strip().lower()):
            if token:
                exts.add(token if token.startswith(".") else f".{token}")
        cached = frozenset(exts)
        _EXT_CACHE[pattern] = cached
    return cached


def match_rule(rule: AutoRule, path: str) -> bool:
    """单条规则对单个路径的匹配判定。"""
    if rule.match_kind == "ext":
        return os.path.splitext(path)[1].lower() in _ext_set(rule.pattern)
    if rule.match_kind == "dir":
        needle = os.path.normcase(rule.pattern.strip())
        return bool(needle) and needle in os.path.normcase(path)
    return False


def _collect_bindings(records: list[FileRecord],
                      rules: list[AutoRule]) -> list[tuple[int, int, str]]:
    return [
        (record.id, rule.tag_id, "auto")
        for record in records for rule in rules if match_rule(rule, record.path)
    ]


class TagRuleEngine:
    """对扫描新增/更新的文件应用规则；支持全量重建。"""

    def __init__(self, db_manager: DatabaseManager):
        self.rule_dao = AutoRuleDAO(db_manager)
        self.tag_dao = TagDAO(db_manager)
        self.file_dao = FileDAO(db_manager)

    def _enabled_rules(self) -> list[AutoRule]:
        return [rule for rule in self.rule_dao.get_all_rules() if rule.enabled]

    def apply_to_paths(self, paths: list[str]) -> int:
        """对给定路径应用启用中的规则，返回新写入的绑定数。"""
        rules = self._enabled_rules()
        if not rules or not paths:
            return 0
        records = self.file_dao.get_records_by_paths(paths)
        return self.tag_dao.bind_tags_bulk(_collect_bindings(records, rules))

    def rebuild_all(self) -> int:
        """清空全部自动标签后按当前规则全量重建（手动标签不受影响）。"""
        rules = self._enabled_rules()
        cleared = self.tag_dao.clear_auto_tags()
        records = self.file_dao.get_all_files()
        applied = self.tag_dao.bind_tags_bulk(_collect_bindings(records, rules))
        logger.info("Rebuild auto tags: cleared %d, rules %d, applied %d",
                    cleared, len(rules), applied)
        return applied
