# === 文件路径: src/ui/dialogs/auto_rule_dialog.py ===
"""自动标签规则管理（模态对话框）：增删规则、启停、一键重建自动标签。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core.models import AutoRule
from src.core.tag_service import TagRuleEngine
from src.db.dao import AutoRuleDAO, TagDAO
from src.db.database import DatabaseManager

KIND_LABELS = {"ext": "扩展名", "dir": "目录"}
KIND_BY_LABEL = {label: kind for kind, label in KIND_LABELS.items()}


class AutoRuleDialog(QDialog):
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动标签规则")
        self.resize(680, 440)

        self.engine = TagRuleEngine(db_manager)
        self.rule_dao = AutoRuleDAO(db_manager)
        self.tag_dao = TagDAO(db_manager)

        layout = QVBoxLayout(self)

        tip = QLabel("扫描新增/更新的文件会按启用中的规则自动打标；改动规则后可点击「重建自动标签」全量重算。")
        tip.setProperty("role", "muted")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # ---- 规则列表 ----
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "类型", "模式", "标签", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        # ---- 新增规则表单 ----
        form = QHBoxLayout()
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("规则名称，如：截图目录")
        self.combo_kind = QComboBox()
        self.combo_kind.addItems(list(KIND_BY_LABEL))
        self.input_pattern = QLineEdit()
        self.input_pattern.setPlaceholderText("模式：jpg, png 或目录片段 screenshots")
        self.combo_tag = QComboBox()
        self.combo_tag.setEditable(True)
        for tag in self.tag_dao.get_all_tags():
            self.combo_tag.addItem(tag.tag_name)
        self.btn_add = QPushButton("添加规则")
        self.btn_add.clicked.connect(self._on_add)
        form.addWidget(self.input_name, 2)
        form.addWidget(self.combo_kind)
        form.addWidget(self.input_pattern, 3)
        form.addWidget(self.combo_tag, 1)
        form.addWidget(self.btn_add)
        layout.addLayout(form)

        # ---- 操作按钮 ----
        buttons = QHBoxLayout()
        self.btn_toggle = QPushButton("启用/停用选中")
        self.btn_delete = QPushButton("删除选中")
        self.btn_rebuild = QPushButton("重建自动标签")
        btn_close = QPushButton("关闭")
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_rebuild.clicked.connect(self._on_rebuild)
        btn_close.clicked.connect(self.accept)
        for w in (self.btn_toggle, self.btn_delete):
            buttons.addWidget(w)
        buttons.addStretch()
        buttons.addWidget(self.btn_rebuild)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)

        self._reload()

    # ==========================================
    # 内部
    # ==========================================
    def _reload(self) -> None:
        rules = self.rule_dao.get_all_rules()
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            values = [rule.name, KIND_LABELS.get(rule.match_kind, rule.match_kind),
                      rule.pattern, rule.tag_name or f"#{rule.tag_id}",
                      "启用" if rule.enabled else "停用"]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, rule.id)
                if col == 4 and not rule.enabled:
                    item.setForeground(Qt.gray)
                self.table.setItem(row, col, item)

    def _selected_rule(self) -> AutoRule | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        rule_id = item.data(Qt.UserRole) if item else None
        if rule_id is None:
            return None
        for rule in self.rule_dao.get_all_rules():
            if rule.id == rule_id:
                return rule
        return None

    # ==========================================
    # 槽
    # ==========================================
    def _on_add(self) -> None:
        name = self.input_name.text().strip()
        pattern = self.input_pattern.text().strip()
        tag_name = self.combo_tag.currentText().strip()
        if not name or not pattern or not tag_name:
            QMessageBox.warning(self, "提示", "规则名称、模式、标签均不能为空。")
            return

        tag_id = self.tag_dao.add_tag(tag_name)
        if tag_id <= 0:
            QMessageBox.warning(self, "提示", "标签创建失败。")
            return
        self.tag_dao.set_tag_auto(tag_id)

        kind = KIND_BY_LABEL[self.combo_kind.currentText()]
        if self.rule_dao.add_rule(name, kind, pattern, tag_id) < 0:
            QMessageBox.warning(self, "提示", "规则写入失败，请查看日志。")
            return

        self.input_name.clear()
        self.input_pattern.clear()
        self._reload()

    def _on_toggle(self) -> None:
        rule = self._selected_rule()
        if rule:
            self.rule_dao.set_rule_enabled(rule.id, 0 if rule.enabled else 1)
            self._reload()

    def _on_delete(self) -> None:
        rule = self._selected_rule()
        if not rule:
            return
        answer = QMessageBox.question(
            self, "删除规则", f"确定删除规则「{rule.name}」吗？\n已打上的自动标签不会被回收（可重建）。")
        if answer == QMessageBox.Yes:
            self.rule_dao.delete_rule(rule.id)
            self._reload()

    def _on_rebuild(self) -> None:
        answer = QMessageBox.question(
            self, "重建自动标签",
            "将清除全部自动标签，并按当前启用中的规则对整个库重新打标。\n手动标签不受影响。确定继续吗？")
        if answer != QMessageBox.Yes:
            return
        applied = self.engine.rebuild_all()
        QMessageBox.information(self, "重建完成", f"已按当前规则重新打标，共写入 {applied} 条自动标签。")
