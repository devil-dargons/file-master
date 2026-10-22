# === 文件路径: src/ui/panels/query_builder_panel.py ===
"""条件构造器面板（M3）：AND/OR 分组组合检索，结果发送到中央文件列表。

面板之间不直接互引：查询请求经 query_requested 信号由主窗口接线转发。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.core.models import Tag, TagGroup, TagQuery
from src.db.dao import TagDAO
from src.db.database import DatabaseManager

OP_LABELS = {"AND": "满足全部分组（且）", "OR": "满足任一分组（或）"}
OP_BY_LABEL = {label: op for op, label in OP_LABELS.items()}


class _GroupEditor(QFrame):
    """单个条件分组：勾选若干标签，组内为 AND 语义。"""

    removed = Signal(object)

    def __init__(self, tags: list[Tag], parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        self.lbl_title = QLabel("分组")
        self.lbl_title.setProperty("role", "mutedBold")
        btn_remove = QPushButton("删除组")
        btn_remove.clicked.connect(lambda: self.removed.emit(self))
        header.addWidget(self.lbl_title)
        header.addStretch()
        header.addWidget(btn_remove)
        layout.addLayout(header)

        self.list_tags = QListWidget()
        for tag in tags:
            item = QListWidgetItem(tag.tag_name)
            item.setData(Qt.UserRole, tag.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_tags.addItem(item)
        self.list_tags.setMaximumHeight(140)
        layout.addWidget(self.list_tags)

    def set_index(self, index: int) -> None:
        self.lbl_title.setText(f"分组 {index}")

    def selected_tag_ids(self) -> list[int]:
        return [
            self.list_tags.item(row).data(Qt.UserRole)
            for row in range(self.list_tags.count())
            if self.list_tags.item(row).checkState() == Qt.Checked
        ]

    def set_checked(self, tag_ids: list[int]) -> None:
        wanted = set(tag_ids)
        for row in range(self.list_tags.count()):
            item = self.list_tags.item(row)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in wanted else Qt.Unchecked)


class QueryBuilderPanel(QWidget):
    query_requested = Signal(object)   # TagQuery

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.tag_dao = TagDAO(db_manager)
        self._groups: list[_GroupEditor] = []

        layout = QVBoxLayout(self)

        tip = QLabel("组内标签必须同时命中；分组之间按下方逻辑组合。")
        tip.setProperty("role", "muted")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("分组间逻辑:"))
        self.combo_op = QComboBox()
        self.combo_op.addItems(list(OP_BY_LABEL))
        op_row.addWidget(self.combo_op, 1)
        layout.addLayout(op_row)

        # 分组滚动区
        self.groups_host = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_host)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.groups_host)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        btn_add_group = QPushButton("＋ 添加分组")
        btn_refresh = QPushButton("刷新标签")
        btn_query = QPushButton("查询")
        btn_query.setObjectName("primaryButton")
        btn_add_group.clicked.connect(lambda: self._add_group())
        btn_refresh.clicked.connect(self._reload_tags)
        btn_query.clicked.connect(self._on_query)
        buttons.addWidget(btn_add_group)
        buttons.addWidget(btn_refresh)
        buttons.addStretch()
        buttons.addWidget(btn_query)
        layout.addLayout(buttons)

        self._tags: list[Tag] = []
        self._reload_tags()
        self._add_group()

    # ==========================================
    # 内部
    # ==========================================
    def _reload_tags(self) -> None:
        """刷新标签清单，保留各组已勾选状态。"""
        checked_per_group = [g.selected_tag_ids() for g in self._groups]
        self._tags = self.tag_dao.get_all_tags()
        for group, checked in zip(self._groups, checked_per_group, strict=False):
            group.list_tags.clear()
            for tag in self._tags:
                item = QListWidgetItem(tag.tag_name)
                item.setData(Qt.UserRole, tag.id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if tag.id in checked else Qt.Unchecked)
                group.list_tags.addItem(item)
        self._reindex()

    def _add_group(self, tag_ids: list[int] | None = None) -> None:
        group = _GroupEditor(self._tags)
        group.removed.connect(self._remove_group)
        if tag_ids:
            group.set_checked(tag_ids)
        self._groups.append(group)
        self.groups_layout.insertWidget(self.groups_layout.count() - 1, group)
        self._reindex()

    def _remove_group(self, group: _GroupEditor) -> None:
        if len(self._groups) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个分组。")
            return
        group.setParent(None)
        group.deleteLater()
        self._groups.remove(group)
        self._reindex()

    def _reindex(self) -> None:
        for index, group in enumerate(self._groups, start=1):
            group.set_index(index)

    # ==========================================
    # 查询
    # ==========================================
    def build_query(self) -> TagQuery:
        groups = [TagGroup(tag_ids=g.selected_tag_ids()) for g in self._groups]
        groups = [g for g in groups if g.tag_ids]
        op = OP_BY_LABEL[self.combo_op.currentText()]
        return TagQuery(op=op, groups=groups)

    def _on_query(self) -> None:
        query = self.build_query()
        if not query.groups:
            QMessageBox.information(self, "提示", "请先在分组中勾选至少一个标签。")
            return
        self.query_requested.emit(query)

    def load_query(self, query: TagQuery) -> None:
        """恢复一个已有查询（预留给保存/回显场景）。"""
        self.combo_op.setCurrentText(OP_LABELS.get(query.op, OP_LABELS["AND"]))
        for group in list(self._groups):
            group.setParent(None)
            group.deleteLater()
        self._groups.clear()
        for tag_group in query.groups:
            self._add_group(tag_group.tag_ids)
