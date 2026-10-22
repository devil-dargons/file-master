# === 文件路径: src/ui/dialogs/lock_dialog.py ===
"""启动锁对话框（M4 安全）。

- 未设置主密码 → 设置模式（输入两遍）
- 已设置 → 验证模式；连续错误达上限后锁定倒计时（QTimer 驱动）
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from src.core.vault import (
    AccountLockedError, UnlockFailedError, VaultError, VaultService,
)


class LockDialog(QDialog):
    """启动锁；accepted = 已设置/验证成功。"""

    def __init__(self, service: VaultService, parent=None):
        super().__init__(parent)
        self.service = service
        self._setup_mode = not service.is_lock_enabled()
        self._countdown: int = 0

        self.setWindowTitle("FileMaster 启动锁")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        title = QLabel("设置主密码（首次使用）" if self._setup_mode
                       else "本库已启用启动保护，请输入主密码")
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()
        self.input_pwd = QLineEdit()
        self.input_pwd.setEchoMode(QLineEdit.Password)
        form.addRow("密码：", self.input_pwd)
        self.input_confirm = QLineEdit()
        self.input_confirm.setEchoMode(QLineEdit.Password)
        self.label_confirm = QLabel("确认密码：")
        form.addRow(self.label_confirm, self.input_confirm)
        layout.addLayout(form)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setProperty("role", "muted")
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)

        self.btn_submit = QPushButton("确定")
        self.btn_submit.setDefault(True)
        self.btn_submit.clicked.connect(self._on_submit)
        layout.addWidget(self.btn_submit)

        if not self._setup_mode:
            self.label_confirm.hide()
            self.input_confirm.hide()
            remaining = service.lockout_remaining()
            if remaining > 0:
                self._start_countdown(remaining)

        self.input_pwd.setFocus()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # ----------------------------------
    def _on_submit(self) -> None:
        if self._countdown > 0:
            return
        pwd = self.input_pwd.text()
        if self._setup_mode:
            confirm = self.input_confirm.text()
            if pwd != confirm:
                self.lbl_msg.setText("两次输入的密码不一致。")
                return
            try:
                self.service.set_master_password(pwd)
            except VaultError as e:
                self.lbl_msg.setText(str(e))
                return
            self.accept()
            return

        try:
            self.service.try_unlock(pwd)
        except AccountLockedError as e:
            self._start_countdown(e.remaining_seconds)
        except UnlockFailedError:
            left = self.service.remaining_attempts()
            self.lbl_msg.setText(f"密码错误。还可尝试 {left} 次。")
            self.input_pwd.selectAll()
            self.input_pwd.setFocus()
        except VaultError as e:
            self.lbl_msg.setText(str(e))
        else:
            self.accept()

    def _start_countdown(self, seconds: int) -> None:
        self._countdown = max(1, seconds)
        self.btn_submit.setEnabled(False)
        self.input_pwd.setEnabled(False)
        self._on_tick()
        self._timer.start()

    def _on_tick(self) -> None:
        if self._countdown <= 1:
            self._timer.stop()
            self._countdown = 0
            self.btn_submit.setEnabled(True)
            self.input_pwd.setEnabled(True)
            self.lbl_msg.setText("锁定已解除，请重试。")
            self.input_pwd.setFocus()
            return
        self._countdown -= 1
        self.lbl_msg.setText(f"错误次数过多，已锁定，剩余 {self._countdown} 秒。")

    # ----------------------------------
    @staticmethod
    def run(service: VaultService, parent=None) -> bool:
        """便捷入口：需要弹锁时返回 True（用户已完成设置/验证）。"""
        if service.is_unlocked():
            return True
        dlg = LockDialog(service, parent)
        result = dlg.exec()
        return result == QDialog.Accepted
