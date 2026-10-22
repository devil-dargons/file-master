# === 文件路径: src/ui/widgets/tag_editor_widget.py ===
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt

from src.db.dao import TagDAO
from src.ui import themes
from src.ui.widgets.flow_layout import FlowLayout


class TagEditorWidget(QWidget):
    """标签编辑内容控件：已有标签以圆角 chip 按钮流式排列（点击切换选中），
    下方输入新标签。

    供 TagManageDialog（弹窗）与 ImageViewer（底部抽拉面板）复用，
    避免两处重复实现同一套勾选/收集逻辑。
    样式跟随全局主题（palette），主题切换后重新打开即生效。
    """

    def __init__(self, tag_dao: TagDAO, parent=None):
        super().__init__(parent)
        self.tag_dao = tag_dao
        self.file_id: int | None = None
        self._chips: list = []  # list[QPushButton]，文本即标签名

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # chip 流式区（可滚动，自动换行）
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.chips_host = QWidget()
        self.flow = FlowLayout(self.chips_host)
        self.scroll.setWidget(self.chips_host)
        layout.addWidget(self.scroll, 1)

        # 新标签输入
        self.new_tag_input = QLineEdit()
        self.new_tag_input.setPlaceholderText("新标签（多个用英文逗号分隔）")
        layout.addWidget(self.new_tag_input)

        self._refresh_chip_styles()

    def _chip_qss(self, checked: bool) -> str:
        """按主题色生成单个 chip 的样式（选中态高亮 accent）。"""
        c = themes.palette.colors(themes.current_theme())
        if checked:
            return (
                f"QPushButton {{ background: {c['accent']}; color: {c['accent_text']};"
                f" border: 1px solid {c['accent']}; border-radius: 11px; padding: 2px 12px; }}"
                f"QPushButton:hover {{ background: {c['accent_hover']}; }}"
            )
        return (
            f"QPushButton {{ background: {c['surface_alt']}; color: {c['text']};"
            f" border: 1px solid {c['border']}; border-radius: 11px; padding: 2px 12px; }}"
            f"QPushButton:hover {{ background: {c['surface_hover']}; }}"
        )

    def _refresh_chip_styles(self) -> None:
        for chip in self._chips:
            chip.setStyleSheet(self._chip_qss(chip.isChecked()))

    def _on_chip_toggled(self, chip: QPushButton) -> None:
        chip.setStyleSheet(self._chip_qss(chip.isChecked()))

    def load_for_file(self, file_id: int) -> None:
        """加载所有标签为 chip 按钮，并按该文件当前绑定状态设置选中。"""
        self.file_id = file_id
        # 清空旧 chips
        while self.flow.count():
            item = self.flow.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._chips.clear()

        file_tag_ids = {t.id for t in self.tag_dao.get_tags_by_file_id(file_id)}
        for tag in self.tag_dao.get_all_tags():
            chip = QPushButton(tag.tag_name)
            chip.setCheckable(True)
            chip.setChecked(tag.id in file_tag_ids)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setFocusPolicy(Qt.NoFocus)
            chip.setStyleSheet(self._chip_qss(chip.isChecked()))
            chip.toggled.connect(lambda _=False, b=chip: self._on_chip_toggled(b))
            self.flow.addWidget(chip)
            self._chips.append(chip)

    def get_tags_to_add(self) -> list[str]:
        """最终需要添加的标签：新输入 + 被选中的 chip（去重）。"""
        new_tags = [t.strip() for t in self.new_tag_input.text().split(',') if t.strip()]
        checked = [chip.text() for chip in self._chips if chip.isChecked()]
        return list(set(new_tags + checked))

    def get_tags_to_remove(self) -> list[str]:
        """需要移除的标签：chip 中未被选中的。"""
        return [chip.text() for chip in self._chips if not chip.isChecked()]

    def clear_new_input(self) -> None:
        self.new_tag_input.clear()
