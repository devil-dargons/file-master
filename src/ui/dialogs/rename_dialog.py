from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QSpinBox, QCheckBox, QPushButton, QTableWidget, 
    QTableWidgetItem, QHeaderView, QAbstractItemView, QLabel 
)
from PySide6.QtCore import Qt

class RenameDialog(QDialog):
    """
    批量重命名规则配置与预览弹窗
    """
    def __init__(self, selected_files: list[dict], parent=None):
        super().__init__(parent)
        self.selected_files = selected_files
        
        # 最终结果映射：{ "旧绝对路径": "新文件名(不含路径)" }
        self.rename_map = {} 
        
        self.setWindowTitle("批量重命名")
        self.setMinimumSize(600, 500)
        self._init_ui()
        self._connect_signals()
        self._update_preview()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # 1. 规则配置区
        rule_group = QGroupBox("重命名规则")
        rule_layout = QFormLayout()
        
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("例如：2024_Report_")
        rule_layout.addRow("前缀:", self.prefix_input)
        
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("例如：_final")
        rule_layout.addRow("后缀:", self.suffix_input)
        
        # 序号配置
        seq_layout = QHBoxLayout()
        self.seq_check = QCheckBox("添加递增序号")
        self.seq_start_spin = QSpinBox()
        self.seq_start_spin.setRange(1, 9999)
        self.seq_start_spin.setValue(1)
        self.seq_digits_spin = QSpinBox()
        self.seq_digits_spin.setRange(1, 5)
        self.seq_digits_spin.setValue(3)
        self.seq_digits_spin.setToolTip("序号位数，如3位则生成 001, 002")
        
        seq_layout.addWidget(self.seq_check)
        seq_layout.addWidget(QLabel("起始:"))
        seq_layout.addWidget(self.seq_start_spin)
        seq_layout.addWidget(QLabel("位数:"))
        seq_layout.addWidget(self.seq_digits_spin)
        seq_layout.addStretch()
        rule_layout.addRow("序号:", seq_layout)
        
        rule_group.setLayout(rule_layout)
        main_layout.addWidget(rule_group)
        
        # 2. 预览区
        preview_group = QGroupBox("预览 (共 {} 个文件发生变化)".format(len(self.selected_files)))
        self.preview_group = preview_group # 保存引用以便更新标题
        preview_layout = QVBoxLayout()
        
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(["原文件名", "新文件名"])
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        
        preview_layout.addWidget(self.preview_table)
        preview_group.setLayout(preview_layout)
        main_layout.addWidget(preview_group, 1) # 拉伸比例为 1，让预览区占据更多空间
        
        # 3. 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton("执行重命名")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 15px;")
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)
        
    def _connect_signals(self):
        """连接信号与槽，实现规则改变时实时刷新预览"""
        self.prefix_input.textChanged.connect(self._update_preview)
        self.suffix_input.textChanged.connect(self._update_preview)
        self.seq_check.stateChanged.connect(self._update_preview)
        self.seq_start_spin.valueChanged.connect(self._update_preview)
        self.seq_digits_spin.valueChanged.connect(self._update_preview)
        
        self.btn_ok.clicked.connect(self._on_accept)
        self.btn_cancel.clicked.connect(self.reject)

    def _generate_new_name(self, original_name: str, index: int) -> str:
        """根据当前 UI 配置，生成单个文件的新名称"""
        # 分离文件名和扩展名 (使用 rsplit 确保只分割最后一个点)
        if '.' in original_name and not original_name.startswith('.'):
            name_part, ext_part = original_name.rsplit('.', 1)
            ext_part = '.' + ext_part
        else:
            name_part = original_name
            ext_part = ''
            
        new_name = ""
        
        # 拼接前缀
        prefix = self.prefix_input.text()
        if prefix:
            new_name += prefix
            
        # 拼接原文件名
        new_name += name_part
        
        # 拼接后缀
        suffix = self.suffix_input.text()
        if suffix:
            new_name += suffix
            
        # 拼接序号
        if self.seq_check.isChecked():
            start = self.seq_start_spin.value()
            digits = self.seq_digits_spin.value()
            seq_num = start + index
            new_name += f"_{str(seq_num).zfill(digits)}"
            
        return new_name + ext_part

    def _update_preview(self):
        """根据规则重新生成预览列表"""
        self.preview_table.setRowCount(0)
        self.rename_map = {}
        
        valid_count = 0
        for i, file_data in enumerate(self.selected_files):
            old_name = file_data['name']
            new_name = self._generate_new_name(old_name, i)
            
            # 只有当新名字和老名字不同时，才加入预览和结果集
            if new_name != old_name:
                valid_count += 1
                self.rename_map[file_data['path']] = new_name
                
                row = self.preview_table.rowCount()
                self.preview_table.insertRow(row)
                
                item_old = QTableWidgetItem(old_name)
                item_new = QTableWidgetItem(new_name)
                # 给新文件名加点颜色提示
                item_new.setForeground(Qt.green) 
                
                self.preview_table.setItem(row, 0, item_old)
                self.preview_table.setItem(row, 1, item_new)
                
        # 更新预览区标题
        self.preview_group.setTitle(f"预览 (共 {valid_count} 个文件发生变化)")
        
        # 自适应列宽
        self.preview_table.resizeColumnsToContents()

    def _on_accept(self):
        """点击确定时的校验"""
        if not self.rename_map:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "没有检测到任何需要重命名的文件，请修改规则。")
            return
            
        self.accept() # 关闭弹窗并返回 Accepted 状态

    def get_rename_map(self) -> dict:
        """
        获取最终的重命名映射字典。
        格式: { "C:/old/path/file.txt": "new_name.txt", ... }
        """
        return self.rename_map