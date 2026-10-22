# === 文件路径: src/ui/widgets/custom_table.py ===
from __future__ import annotations
from PySide6.QtWidgets import QTableWidget, QHeaderView, QAbstractItemView, QTableWidgetItem
from PySide6.QtCore import Qt, Signal, QPoint

class CustomTable(QTableWidget):
    row_right_clicked = Signal(int, dict, QPoint)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # 核心改动：允许编辑触发选择，从而支持 Ctrl+C 复制文本
        self.setEditTriggers(QAbstractItemView.NoEditTriggers) 
        self.setFocusPolicy(Qt.StrongFocus) # 确保能接收键盘事件
        
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.verticalHeader().setVisible(False)
        
    def set_columns(self, columns: list[str]):
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        
    def load_data(self, data: list, columns_mapping: list[str]):
        """加载数据。行对象支持 dataclass（属性访问）与 dict（.get 访问）。"""
        self.clearContents()
        self.setRowCount(len(data))

        for row_idx, row_data in enumerate(data):
            for col_idx, key in enumerate(columns_mapping):
                value = self._get_value(row_data, key)
                item = QTableWidgetItem(value)
                if col_idx == 0:
                    item.setData(Qt.UserRole, row_data)
                self.setItem(row_idx, col_idx, item)

        self.resizeColumnsToContents()

    @staticmethod
    def _get_value(row_data, key: str) -> str:
        if isinstance(row_data, dict):
            value = row_data.get(key, "")
        else:
            value = getattr(row_data, key, "")
        return "" if value is None else str(value)

    def get_selected_rows_data(self) -> list:
        selected_items = self.selectedItems()
        rows = sorted(set(item.row() for item in selected_items))
        result = []
        for row in rows:
            first_col_item = self.item(row, 0)
            if first_col_item:
                data = first_col_item.data(Qt.UserRole)
                if data:
                    result.append(data)
        return result

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            row = item.row()
            first_col_item = self.item(row, 0)
            data = first_col_item.data(Qt.UserRole) if first_col_item else {}
            global_pos = self.mapToGlobal(event.pos())
            self.row_right_clicked.emit(row, data or {}, global_pos)