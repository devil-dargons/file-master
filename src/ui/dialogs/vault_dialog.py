# === 文件路径: src/ui/dialogs/vault_dialog.py ===
"""加密保险库管理对话框（M4 安全）。

- 列表：vault_items（原文件名 / 大小 / 入库时间）
- 操作：加密入库（后台线程） / 预览 / 导出明文 / 移除
- 安全维护：修改主密码（重 wrap，秒级） / 加密备份导出 / 备份恢复
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core.vault import VaultError, VaultService

logger = logging.getLogger(__name__)


def show_change_password_dialog(service: VaultService, parent=None) -> None:
    """修改主密码对话框（独立复用入口，供 VaultDialog / SettingsDialog 共用）。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle("修改主密码")
    form = QVBoxLayout(dlg)
    old_edit = QLineEdit(); old_edit.setEchoMode(QLineEdit.Password)
    new_edit = QLineEdit(); new_edit.setEchoMode(QLineEdit.Password)
    confirm_edit = QLineEdit(); confirm_edit.setEchoMode(QLineEdit.Password)
    form.addWidget(QLabel("原密码（当前为空则留空）：")); form.addWidget(old_edit)
    form.addWidget(QLabel("新密码（留空表示无密码，但仍会弹输入框）：")); form.addWidget(new_edit)
    form.addWidget(QLabel("确认新密码：")); form.addWidget(confirm_edit)
    btn = QPushButton("确定修改")
    form.addWidget(btn)

    def submit() -> None:
        if new_edit.text() != confirm_edit.text():
            QMessageBox.warning(dlg, "修改主密码", "两次输入的新密码不一致。")
            return
        try:
            n = service.change_master_password(old_edit.text(), new_edit.text())
        except VaultError as e:
            QMessageBox.warning(dlg, "修改主密码", str(e))
            return
        msg = f"主密码已修改，已重 wrap {n} 个文件密钥（文件体无需重加密）。"
        if not new_edit.text():
            msg += "\n\n注意：当前密码为空，下次启动时直接点击确定即可通过。"
        QMessageBox.information(dlg, "修改主密码", msg)
        dlg.accept()

    btn.clicked.connect(submit)
    dlg.exec()


def _fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class VaultDialog(QDialog):
    # 工作线程 → UI 的进度信号（跨线程排队投递）
    _progress = Signal(int, int, str)
    _work_done = Signal(bool, str)

    def __init__(self, service: VaultService, parent=None):
        super().__init__(parent)
        self.service = service
        self._worker: threading.Thread | None = None
        self._preview_dialog: QDialog | None = None
        self._item_ids: list[int] = []

        self.setWindowTitle("加密保险库")
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        count, total = service.get_stats()
        self.lbl_stats = QLabel(f"共 {count} 个条目，密文占用 {_fmt_size(total)}")
        self.lbl_stats.setProperty("role", "muted")
        layout.addWidget(self.lbl_stats)

        # ---- 条目列表 ----
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["原文件名", "大小", "入库时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        # ---- 操作按钮 ----
        row1 = QHBoxLayout()
        self.btn_add = QPushButton("加密入库…")
        self.btn_preview = QPushButton("预览")
        self.btn_export = QPushButton("导出明文…")
        self.btn_remove = QPushButton("移除")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_remove.clicked.connect(self._on_remove)
        for w in (self.btn_add, self.btn_preview, self.btn_export, self.btn_remove):
            row1.addWidget(w)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_change_pwd = QPushButton("修改主密码…")
        self.btn_backup = QPushButton("导出加密备份…")
        self.btn_restore = QPushButton("恢复备份…")
        self.btn_change_pwd.clicked.connect(self._on_change_password)
        self.btn_backup.clicked.connect(self._on_backup)
        self.btn_restore.clicked.connect(self._on_restore)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row2.addWidget(self.btn_change_pwd)
        row2.addWidget(self.btn_backup)
        row2.addWidget(self.btn_restore)
        row2.addStretch()
        row2.addWidget(btn_close)
        layout.addLayout(row2)

        self._progress.connect(self._on_progress)
        self._work_done.connect(self._on_work_done)
        self._reload()

    # ==========================================
    # 列表
    # ==========================================
    def _reload(self) -> None:
        items = self.service._vault.list_items()
        self._item_ids = [item.id for item in items]
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.original_name))
            self.table.setItem(row, 1, QTableWidgetItem(_fmt_size(item.orig_size)))
            ts = datetime.fromtimestamp(item.added_time).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(row, 2, QTableWidgetItem(ts))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        count, total = self.service.get_stats()
        self.lbl_stats.setText(f"共 {count} 个条目，密文占用 {_fmt_size(total)}")

    def _selected_item_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._item_ids):
            return None
        return self._item_ids[row]

    # ==========================================
    # 加密入库（后台线程）
    # ==========================================
    def _on_add(self) -> None:
        if self._worker and self._worker.is_alive():
            QMessageBox.information(self, "提示", "入库任务正在进行中。")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要加密入库的文件")
        if not paths:
            return

        def worker() -> None:
            ok, fail = 0, 0
            total = len(paths)
            for i, path in enumerate(paths, 1):
                try:
                    self.service.encrypt_into_vault(path)
                    ok += 1
                    self._progress.emit(i, total, path)
                except Exception as e:  # 单个失败不中断批次
                    logger.warning("Vault encrypt failed for %s: %s", path, e)
                    self._progress.emit(i, total, f"{path}（失败：{e}）")
                    fail += 1
            self._work_done.emit(fail == 0, f"加密入库完成：成功 {ok}，失败 {fail}")

        self._set_busy(True)
        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        for btn in (self.btn_add, self.btn_preview, self.btn_export,
                    self.btn_remove, self.btn_change_pwd, self.btn_backup, self.btn_restore):
            btn.setEnabled(not busy)
        self.setWindowTitle("加密保险库（处理中…）" if busy else "加密保险库")

    def _on_progress(self, current: int, total: int, path: str) -> None:
        self.lbl_stats.setText(f"处理中 {current}/{total}：{path}")

    def _on_work_done(self, success: bool, message: str) -> None:
        self._set_busy(False)
        if success:
            QMessageBox.information(self, "加密入库", message)
        else:
            QMessageBox.warning(self, "加密入库", message)
        self._reload()

    # ==========================================
    # 预览 / 导出 / 移除
    # ==========================================
    def _on_preview(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(self, "预览", "请先选择一个条目。")
            return
        try:
            data = self.service.decrypt_to_bytes(item_id)
        except VaultError as e:
            QMessageBox.warning(self, "预览", str(e))
            return

        pix = QPixmap()
        if pix.loadFromData(data):
            self._preview_dialog = QDialog(self)
            self._preview_dialog.setWindowTitle("解密预览（仅内存，不落盘）")
            v = QVBoxLayout(self._preview_dialog)
            label = QLabel()
            label.setPixmap(pix.scaled(
                720, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            label.setFixedSize(QSize(740, 500))
            label.setAlignment(Qt.AlignCenter)
            v.addWidget(label)
            self._preview_dialog.show()
            return

        try:
            text = data.decode("utf-8")
            if text.count("\x00"):  # 二进制误判为文本
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "nul bytes")
        except (UnicodeDecodeError, ValueError):
            QMessageBox.information(
                self, "预览", "该文件不支持直接预览，请使用「导出明文…」查看。")
            return
        self._preview_dialog = QDialog(self)
        self._preview_dialog.setWindowTitle("解密预览（仅内存，不落盘）")
        v = QVBoxLayout(self._preview_dialog)
        text_label = QLabel(text[:20000])
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(text_label)
        self._preview_dialog.resize(640, 480)
        self._preview_dialog.show()

    def _on_export(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(self, "导出明文", "请先选择一个条目。")
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "选择明文导出目录")
        if not dest_dir:
            return
        try:
            dest = self.service.export_plaintext(item_id, dest_dir)
        except VaultError as e:
            QMessageBox.warning(self, "导出明文", str(e))
            return
        QMessageBox.information(
            self, "导出明文", f"已导出到：\n{dest}\n\n注意：明文导出后请用后即焚。")

    def _on_remove(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(self, "移除", "请先选择一个条目。")
            return
        answer = QMessageBox.question(
            self, "移除条目",
            "将从保险库移除该条目并删除密文文件（原文件不会恢复）。\n确定继续吗？")
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.remove_from_vault(item_id)
        except VaultError as e:
            QMessageBox.warning(self, "移除", str(e))
            return
        self._reload()

    # ==========================================
    # 修改主密码 / 备份
    # ==========================================
    def _on_change_password(self) -> None:
        show_change_password_dialog(self.service, self)

    def _on_backup(self) -> None:
        default = f"filemaster_{datetime.now().strftime('%Y%m%d_%H%M%S')}.fmbackup"
        out, _ = QFileDialog.getSaveFileName(
            self, "导出加密备份", default, "FileMaster 加密备份 (*.fmbackup)")
        if not out:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("备份密码")
        v = QVBoxLayout(dlg)
        pwd_edit = QLineEdit(); pwd_edit.setEchoMode(QLineEdit.Password)
        v.addWidget(QLabel("备份密码（独立于主密码，用于恢复此备份）："))
        v.addWidget(pwd_edit)
        btn = QPushButton("开始导出")
        v.addWidget(btn)

        def submit() -> None:
            try:
                self.service.export_encrypted_backup(out, pwd_edit.text())
            except VaultError as e:
                QMessageBox.warning(dlg, "导出加密备份", str(e))
                return
            QMessageBox.information(dlg, "导出加密备份", f"备份已导出到：\n{out}")
            dlg.accept()

        btn.clicked.connect(submit)
        dlg.exec()

    def _on_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "", "FileMaster 加密备份 (*.fmbackup)")
        if not path:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "恢复到", "restored_filemaster.db", "SQLite 数据库 (*.db)")
        if not out:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("备份密码")
        v = QVBoxLayout(dlg)
        pwd_edit = QLineEdit(); pwd_edit.setEchoMode(QLineEdit.Password)
        v.addWidget(QLabel("输入该备份的密码："))
        v.addWidget(pwd_edit)
        btn = QPushButton("开始恢复")
        v.addWidget(btn)

        def submit() -> None:
            try:
                dest = self.service.restore_encrypted_backup(path, out, pwd_edit.text())
            except VaultError as e:
                QMessageBox.warning(dlg, "恢复备份", str(e))
                return
            QMessageBox.information(
                dlg, "恢复备份", f"恢复成功：\n{dest}\n\n如需启用，请将该文件重命名为 filemaster.db 并重启应用。")
            dlg.accept()

        btn.clicked.connect(submit)
        dlg.exec()
