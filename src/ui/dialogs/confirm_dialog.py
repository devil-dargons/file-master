from __future__ import annotations

import os
from PySide6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QRadioButton, QCheckBox, QPushButton, QButtonGroup
)

# 引入 Core 层定义的冲突策略常量，保证 UI 和后端逻辑的一致性
from src.core.file_service import STRATEGY_OVERWRITE, STRATEGY_SKIP, STRATEGY_RENAME

class ConfirmDialog:
    """
    弹窗工具类
    提供各类确认、选择对话框，收集用户意图并返回给 UI 面板处理。
    """
    
    @staticmethod
    def show_confirm(title: str, message: str, parent=None) -> bool:
        """显示简单的 Yes/No 确认弹窗（如删除前确认）"""
        reply = QMessageBox.question(
            parent, title, message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # 默认焦点在 No 上，防止误触回车
        )
        return reply == QMessageBox.Yes

    @staticmethod
    def show_confirm_with_remember(title: str, message: str, remember_text: str, parent=None) -> tuple[bool, bool]:
        """显示带“记住选择”复选框的 Yes/No 确认弹窗。

        :return: (是否确认, 是否勾选了记住)
        """
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Question)
        box.setText(message)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)  # 默认焦点在 No 上，防止误触回车
        cb_remember = QCheckBox(remember_text)
        box.setCheckBox(cb_remember)
        reply = box.exec()
        return reply == QMessageBox.Yes, cb_remember.isChecked()

    @staticmethod
    def show_conflict_dialog(file_name: str, target_dir: str, parent=None) -> tuple[str | None, bool]:
        """
        显示文件冲突处理弹窗。
        :param file_name: 发生冲突的文件名
        :param target_dir: 目标文件夹路径
        :param parent: 父窗口
        :return: (策略字符串, 是否应用到所有同名冲突)。如果用户取消，策略为 None。
        """
        dialog = QDialog(parent)
        dialog.setWindowTitle("文件冲突")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # 1. 提示信息
        conflict_path = os.path.join(target_dir, file_name)
        msg = f"目标文件夹中已存在同名文件：\n\n{conflict_path}\n\n请选择处理方式："
        label = QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # 2. 单选按钮组 (策略选择)
        radio_group = QButtonGroup(dialog)
        
        rb_skip = QRadioButton("跳过 (不处理此文件)")
        rb_overwrite = QRadioButton("覆盖 (替换已有文件)")
        rb_rename = QRadioButton("自动重命名 (如 file_1.txt)")
        
        rb_skip.setChecked(True)  # 默认选择最安全的“跳过”
        
        radio_group.addButton(rb_skip, 0)
        radio_group.addButton(rb_overwrite, 1)
        radio_group.addButton(rb_rename, 2)
        
        layout.addWidget(rb_skip)
        layout.addWidget(rb_overwrite)
        layout.addWidget(rb_rename)
        
        layout.addSpacing(15)
        
        # 3. “应用到所有”复选框
        cb_apply_all = QCheckBox("将此操作应用到所有冲突的文件 (不再弹窗)")
        layout.addWidget(cb_apply_all)
        
        # 4. 底部确认/取消按钮
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        
        # 映射 UI 选项 ID 到 Core 层定义的常量字符串
        strategy_map = {
            0: STRATEGY_SKIP,
            1: STRATEGY_OVERWRITE,
            2: STRATEGY_RENAME
        }
        
        # 执行弹窗，等待用户操作
        if dialog.exec() == QDialog.Accepted:
            selected_id = radio_group.checkedId()
            strategy = strategy_map.get(selected_id, STRATEGY_SKIP)
            apply_all = cb_apply_all.isChecked()
            return strategy, apply_all
        else:
            # 用户点击了取消
            return None, False