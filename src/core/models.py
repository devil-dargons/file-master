# === 文件路径: src/core/models.py ===
"""层间数据模型（dataclass）。

铁律：core / db 层禁止 import PySide6；跨层数据一律使用本模块模型，禁止裸 dict。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class FileRecord:
    """files 表一行记录（v2 schema）。"""

    id: int
    path: str
    name: str
    size: int
    modified_time: float
    md5: str
    added_time: float
    thumbnail_path: str | None = None
    file_type: str = "other"
    md5_state: int = 0
    missing: int = 0

    # ---- UI 展示补充字段（由 UI 层填充，非数据库字段）----
    file_category: str = ""
    tags_str: str = ""
    status_str: str = ""
    meta: "MediaMeta | None" = None

    @classmethod
    def from_row(cls, row) -> FileRecord:
        def g(key: str, default=None):
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        return cls(
            id=g("id", 0),
            path=g("path", ""),
            name=g("name", ""),
            size=g("size", 0),
            modified_time=g("modified_time", 0.0),
            md5=g("md5", ""),
            added_time=g("added_time", 0.0),
            thumbnail_path=g("thumbnail_path"),
            file_type=g("file_type", "other"),
            md5_state=g("md5_state", 0),
            missing=g("missing", 0),
        )


@dataclass
class MediaMeta:
    """file_meta 表一行记录（L2 元数据）。"""

    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    page_count: int | None = None
    shot_time: str | None = None
    camera: str | None = None

    @classmethod
    def from_row(cls, row) -> MediaMeta:
        return cls(
            width=row["width"],
            height=row["height"],
            duration_sec=row["duration_sec"],
            page_count=row["page_count"],
            shot_time=row["shot_time"],
            camera=row["camera"],
        )


@dataclass
class Tag:
    """tags 表一行记录。"""

    id: int
    tag_name: str
    color: str | None = None
    is_auto: int = 0

    @classmethod
    def from_row(cls, row) -> Tag:
        def g(key: str, default=None):
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        return cls(
            id=g("id", 0),
            tag_name=g("tag_name", ""),
            color=g("color"),
            is_auto=g("is_auto", 0),
        )


@dataclass
class AutoRule:
    """auto_rules 表一行记录（L1 自动打标规则）。

    match_kind: 'ext'（扩展名列表）| 'dir'（目录路径片段）；pattern 为对应模式串。
    tag_name 仅为 UI 联表展示字段。
    """

    id: int
    name: str
    match_kind: str
    pattern: str
    tag_id: int
    enabled: int = 1
    tag_name: str = ""

    @classmethod
    def from_row(cls, row) -> AutoRule:
        def g(key: str, default=None):
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        return cls(
            id=g("id", 0),
            name=g("name", ""),
            match_kind=g("match_kind", "ext"),
            pattern=g("pattern", ""),
            tag_id=g("tag_id", 0),
            enabled=g("enabled", 1),
            tag_name=g("tag_name", ""),
        )


@dataclass
class TagGroup:
    """标签条件分组：组内所有标签必须同时命中（AND）。"""

    tag_ids: list[int] = field(default_factory=list)


@dataclass
class TagQuery:
    """组合标签查询：分组间按 op 连接（AND=全部满足 / OR=任一满足）。"""

    op: str = "AND"
    groups: list[TagGroup] = field(default_factory=list)


@dataclass
class DuplicateGroup:
    """去重结果分组。"""

    md5: str
    files: list[FileRecord] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.files)


@dataclass
class VaultItem:
    """vault_items 表一行记录（M4 加密区）。"""

    id: int
    original_path: str
    enc_path: str
    enc_size: int
    orig_size: int
    wrapped_dek: bytes
    nonce: bytes
    added_time: float

    @classmethod
    def from_row(cls, row) -> VaultItem:
        def g(key: str, default=None):
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        return cls(
            id=g("id", 0),
            original_path=g("original_path", ""),
            enc_path=g("enc_path", ""),
            enc_size=g("enc_size", 0),
            orig_size=g("orig_size", 0),
            wrapped_dek=g("wrapped_dek", b"") or b"",
            nonce=g("nonce", b"") or b"",
            added_time=g("added_time", 0.0),
        )

    @property
    def original_name(self) -> str:
        return os.path.basename(self.original_path)


@dataclass
class ConsolidatedLink:
    """consolidated_links 表一行记录（M5 归集区）。"""

    id: int
    file_id: int
    link_path: str
    created_time: float

    @classmethod
    def from_row(cls, row) -> ConsolidatedLink:
        def g(key: str, default=None):
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        return cls(
            id=g("id", 0),
            file_id=g("file_id", 0),
            link_path=g("link_path", ""),
            created_time=g("created_time", 0.0),
        )


@dataclass
class OperationResult:
    """FileService 统一操作结果。"""

    success: bool
    message: str
    success_count: int = 0
    fail_count: int = 0
    errors: list[str] = field(default_factory=list)
