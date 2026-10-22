# === 文件路径: src/ui/dialogs/settings_dialog.py ===
"""设置中心（M7，模态对话框，开发手册 5.9）。

- 数据目录：当前路径 + 占用统计；「更改数据目录」触发 5.1 迁移流程
  （预检查 → 暂停后台任务 → 迁移 → 校验 → 写指针；失败自动回滚）
- 缓存维护：缩略图占用统计与清理、数据库 VACUUM
- 安全入口：主密码 / 保险库在「工具 → 加密保险库」，备份导出亦在其中
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressDialog, QPushButton, QSpinBox, QVBoxLayout,
)

from src import config
from src.core.data_migration import DataDirMigrator
from src.core.maintenance import clear_thumbnail_cache, dir_stats

logger = logging.getLogger(__name__)

SETTING_LAN_PORT = "lan_port"
DEFAULT_LAN_PORT = 8765


def _fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class SettingsDialog(QDialog):
    # 工作线程 → UI 信号
    _mig_done = Signal(bool, str)

    def __init__(self, main_window, db_manager, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.db = db_manager
        self._worker: threading.Thread | None = None
        self._progress: QProgressDialog | None = None

        self.setWindowTitle("设置中心")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        # ---- 数据目录 ----
        grp_dir = QGroupBox("数据目录")
        form = QFormLayout(grp_dir)
        self.lbl_dir = QLabel(str(config.APPDATA_DIR))
        self.lbl_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_usage = QLabel()
        self.lbl_usage.setProperty("role", "muted")
        self.btn_change_dir = QPushButton("更改数据目录…")
        self.btn_change_dir.clicked.connect(self._on_change_data_dir)
        row = QHBoxLayout()
        row.addWidget(self.btn_change_dir)
        row.addStretch()
        form.addRow("当前目录：", self.lbl_dir)
        form.addRow("占用：", self.lbl_usage)
        form.addRow("", row)
        layout.addWidget(grp_dir)

        # ---- 缓存维护 ----
        grp_maint = QGroupBox("缓存维护")
        mrow = QHBoxLayout(grp_maint)
        self.lbl_thumb_usage = QLabel()
        self.lbl_thumb_usage.setProperty("role", "muted")
        self.btn_clear_thumbs = QPushButton("清理缩略图缓存")
        self.btn_clear_thumbs.clicked.connect(self._on_clear_thumbs)
        self.btn_vacuum = QPushButton("数据库整理（VACUUM）")
        self.btn_vacuum.clicked.connect(self._on_vacuum)
        mrow.addWidget(self.lbl_thumb_usage)
        mrow.addStretch()
        mrow.addWidget(self.btn_clear_thumbs)
        mrow.addWidget(self.btn_vacuum)
        layout.addWidget(grp_maint)

        # ---- 安全 ----
        grp_sec = QGroupBox("安全")
        sec_layout = QVBoxLayout(grp_sec)
        sec_tip = QLabel("主密码与启动锁在首次启动时设置；加密文件、加密备份请使用「工具 → 加密保险库」。")
        sec_tip.setWordWrap(True)
        sec_layout.addWidget(sec_tip)
        sec_btn_row = QHBoxLayout()
        self.btn_change_pwd = QPushButton("修改主密码…")
        self.btn_change_pwd.clicked.connect(self._on_change_password)
        sec_btn_row.addWidget(self.btn_change_pwd)
        sec_btn_row.addStretch()
        sec_layout.addLayout(sec_btn_row)
        layout.addWidget(grp_sec)

        # ---- 局域网服务（手机访问） ----
        grp_lan = QGroupBox("局域网服务（手机浏览器访问）")
        lan_layout = QVBoxLayout(grp_lan)

        self.lbl_lan_status = QLabel()
        self.lbl_lan_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_lan_status.setWordWrap(True)
        lan_layout.addWidget(self.lbl_lan_status)

        lan_row = QHBoxLayout()
        lan_row.addWidget(QLabel("端口："))
        self.spin_lan_port = QSpinBox()
        self.spin_lan_port.setRange(1024, 65535)
        self.spin_lan_port.setValue(self._load_lan_port())
        lan_row.addWidget(self.spin_lan_port)
        self.btn_lan_toggle = QPushButton()
        self.btn_lan_toggle.clicked.connect(self._on_lan_toggle)
        lan_row.addWidget(self.btn_lan_toggle)
        lan_row.addStretch()
        lan_layout.addLayout(lan_row)

        lan_tip = QLabel("启动后，手机与电脑连接同一 Wi-Fi，浏览器访问上方地址；需输入主密码进入。\n"
                         "若手机无法打开页面，请在 Windows 防火墙中允许本程序的入站连接。")
        lan_tip.setProperty("role", "muted")
        lan_tip.setWordWrap(True)
        lan_layout.addWidget(lan_tip)
        layout.addWidget(grp_lan)

        self._refresh_lan_status()

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        brow = QHBoxLayout()
        brow.addStretch()
        brow.addWidget(btn_close)
        layout.addLayout(brow)

        self._mig_done.connect(self._on_mig_done)
        self._refresh_stats()

    # ==========================================
    # 统计
    # ==========================================
    def _refresh_stats(self) -> None:
        total, _ = dir_stats(config.APPDATA_DIR)
        self.lbl_usage.setText(_fmt_size(total))
        thumb_bytes, thumb_count = dir_stats(config.THUMBNAIL_DIR)
        self.lbl_thumb_usage.setText(
            f"缩略图缓存：{_fmt_size(thumb_bytes)}（{thumb_count} 个文件）")

    # ==========================================
    # 数据目录迁移
    # ==========================================
    def _on_change_data_dir(self) -> None:
        if self._worker and self._worker.is_alive():
            QMessageBox.information(self, "迁移", "迁移任务正在进行中。")
            return
        new_dir = QFileDialog.getExistingDirectory(self, "选择新的数据目录")
        if not new_dir:
            return

        migrator = DataDirMigrator(self.db)
        reason = migrator.precheck(new_dir)
        if reason:
            QMessageBox.warning(self, "更改数据目录", f"预检查未通过：\n{reason}")
            return
        answer = QMessageBox.question(
            self, "更改数据目录",
            "将执行数据目录迁移：\n"
            "1. 暂停后台任务（扫描/元数据/缩略图）\n"
            "2. 复制数据库与 thumbnails/vault/backups 到新目录\n"
            "3. 校验一致后写入目录指针\n\n"
            "过程失败会自动回滚，旧目录保持原样。完成后需重启应用。\n确定继续吗？",
        )
        if answer != QMessageBox.Yes:
            return

        self.main_window.stop_background_tasks()
        self._set_buttons_enabled(False)
        self._progress = QProgressDialog("正在迁移数据目录…", "", 0, 0, self)
        self._progress.setWindowTitle("数据目录迁移")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setCancelButton(None)
        self._progress.setMinimumDuration(0)
        self._progress.show()

        def on_progress(msg: str) -> None:
            self._progress.setLabelText(msg)

        def worker() -> None:
            result = migrator.migrate(new_dir, progress=on_progress)
            self._mig_done.emit(result.success, result.message)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _on_mig_done(self, success: bool, message: str) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        self._set_buttons_enabled(True)
        if success:
            QMessageBox.information(self, "数据目录迁移", f"{message}。")
            self.accept()
        else:
            QMessageBox.warning(self, "数据目录迁移", message)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_change_dir.setEnabled(enabled)
        self.btn_clear_thumbs.setEnabled(enabled)
        self.btn_vacuum.setEnabled(enabled)
        self.btn_change_pwd.setEnabled(enabled)

    # ==========================================
    # 安全
    # ==========================================
    def _on_change_password(self) -> None:
        from src.core.vault import VaultService
        from src.db.dao import VaultDAO
        from src.ui.dialogs.vault_dialog import show_change_password_dialog
        if self.main_window.vault_service is None:
            self.main_window.vault_service = VaultService(
                self.main_window.db_manager, self.main_window.settings_dao,
                VaultDAO(self.main_window.db_manager), config.VAULT_DIR,
            )
        show_change_password_dialog(self.main_window.vault_service, self)

    # ==========================================
    # 局域网服务
    # ==========================================
    def _load_lan_port(self) -> int:
        raw = self.main_window.settings_dao.get_setting(SETTING_LAN_PORT, str(DEFAULT_LAN_PORT))
        try:
            port = int(raw)
            return port if 1024 <= port <= 65535 else DEFAULT_LAN_PORT
        except (TypeError, ValueError):
            return DEFAULT_LAN_PORT

    def _refresh_lan_status(self) -> None:
        url = self.main_window.lan_server_url()
        if url:
            self.lbl_lan_status.setText(f"状态：运行中 — {url}")
            self.btn_lan_toggle.setText("停止服务")
            self.spin_lan_port.setEnabled(False)
        else:
            self.lbl_lan_status.setText("状态：已停止")
            self.btn_lan_toggle.setText("启动服务")
            self.spin_lan_port.setEnabled(True)

    def _on_lan_toggle(self) -> None:
        if self.main_window.lan_server_url():
            self.main_window.stop_lan_server()
        else:
            port = self.spin_lan_port.value()
            ok, msg = self.main_window.start_lan_server(port)
            if not ok:
                QMessageBox.warning(self, "局域网服务", f"启动失败：{msg}")
            else:
                self.main_window.settings_dao.set_setting(SETTING_LAN_PORT, str(port))
        self._refresh_lan_status()

    # ==========================================
    # 缓存维护
    # ==========================================
    def _on_clear_thumbs(self) -> None:
        answer = QMessageBox.question(
            self, "清理缩略图缓存",
            "将删除全部缩略图缓存文件（可重新生成）。\n确定继续吗？")
        if answer != QMessageBox.Yes:
            return
        removed = clear_thumbnail_cache(config.THUMBNAIL_DIR)
        self._refresh_stats()
        QMessageBox.information(self, "清理缩略图缓存", f"已删除 {removed} 个缩略图文件。")

    def _on_vacuum(self) -> None:
        self._set_buttons_enabled(False)
        try:
            ok = self.db.vacuum()
        finally:
            self._set_buttons_enabled(True)
        if ok:
            self._refresh_stats()
            QMessageBox.information(self, "数据库整理", "VACUUM 完成，数据库文件已整理。")
        else:
            QMessageBox.warning(self, "数据库整理", "VACUUM 失败，请查看日志。")
