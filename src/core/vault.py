# === 文件路径: src/core/vault.py ===
"""安全模块（开发手册 5.6）：启动锁 / Vault 文件加密区 / 加密备份。

设计：
- 主密码哈希（argon2id, PasswordHasher）存 settings 表，仅用于启动锁验证
- 文件加密用每文件随机 32B DEK + AES-256-GCM；DEK 用主密码派生的 KEK 包裹后入库
- 修改主密码只重 wrap 全部 DEK（不重加密文件体），秒级完成
- 加密备份：Fernet 加密的库文件快照，格式 magic(8) + salt(16) + token
- 本模块无 Qt 依赖；耗时操作由 UI 层决定是否放后台线程
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from send2trash import send2trash

from src.db.dao import SettingsDAO, VaultDAO
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

# ---- settings 表 key ----
KEY_MASTER_HASH = "master_hash"        # argon2id PasswordHasher 哈希（启动锁验证用）
KEY_MASTER_SALT = "master_salt"        # base64(argon2id 盐)，KEK 派生用
KEY_LOCK_FAIL_COUNT = "lock_fail_count"
KEY_LOCK_UNTIL = "lock_until"          # epoch 秒

# ---- 加密常量 ----
MAGIC = b"FMBAK01"
SALT_LEN = 16
DEK_LEN = 32
NONCE_LEN = 12
KEK_LEN = 32
_AAD_BODY = b"filemaster:vault:body"
_AAD_DEK = b"filemaster:vault:dek"

# argon2id KEK 派生参数（64MB 内存，桌面单用户可接受）
KEK_TIME_COST = 2
KEK_MEMORY_COST = 65536
KEK_PARALLELISM = 1

_password_hasher = PasswordHasher()  # 启动锁验证（默认参数即可）


class VaultError(Exception):
    """Vault 通用错误。"""


class VaultLockedError(VaultError):
    """会话未解锁（未输入主密码）。"""


class UnlockFailedError(VaultError):
    """密码错误。"""


class AccountLockedError(VaultError):
    """连续错误达上限，账户暂时锁定。"""

    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = remaining_seconds
        super().__init__(f"已锁定，请 {remaining_seconds} 秒后重试")


def derive_kek(password: str, salt: bytes) -> bytes:
    """主密码 → argon2id → 32B KEK。"""
    return hash_secret_raw(
        password.encode("utf-8"), salt,
        KEK_TIME_COST, KEK_MEMORY_COST, KEK_PARALLELISM, KEK_LEN, Type.ID,
    )


def _gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """返回 (nonce, ciphertext)。"""
    nonce = secrets.token_bytes(NONCE_LEN)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def _gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


class VaultService:
    """启动锁 + Vault 加密区 + 加密备份的门面服务。"""

    def __init__(self, db_manager: DatabaseManager, settings_dao: SettingsDAO,
                 vault_dao: VaultDAO, vault_dir: Path, *,
                 max_fail: int = 5, lockout_seconds: int = 60):
        self._db = db_manager
        self._settings = settings_dao
        self._vault = vault_dao
        self._vault_dir = Path(vault_dir)
        self._max_fail = max_fail
        self._lockout_seconds = lockout_seconds
        self._kek: bytes | None = None  # 解锁后缓存在进程内

    # ==========================================
    # 启动锁
    # ==========================================
    def is_lock_enabled(self) -> bool:
        return bool(self._settings.get_setting(KEY_MASTER_HASH))

    def is_unlocked(self) -> bool:
        return self._kek is not None

    def lock(self) -> None:
        """主动清除进程内 KEK 缓存（重新锁定会话）。"""
        self._kek = None

    def lockout_remaining(self) -> int:
        until = float(self._settings.get_setting(KEY_LOCK_UNTIL, "0") or 0)
        return max(0, int(until - time.time()))

    def remaining_attempts(self) -> int:
        fails = int(self._settings.get_setting(KEY_LOCK_FAIL_COUNT, "0") or 0)
        return max(0, self._max_fail - fails)

    def set_master_password(self, password: str) -> None:
        """首次设置主密码（已设置则拒绝）。设置后当前会话即为解锁态。

        允许空字符串（空密码）：is_lock_enabled() 仍返回 True，启动锁界面照常弹出，
        用户直接留空点确定即可通过。仅用于用户明确想取消密码保护但仍保留交互仪式感的场景。
        """
        if self.is_lock_enabled():
            raise VaultError("主密码已设置，请使用修改密码功能")
        salt = secrets.token_bytes(SALT_LEN)
        self._settings.set_setting(KEY_MASTER_SALT, base64.b64encode(salt).decode())
        self._settings.set_setting(KEY_MASTER_HASH, _password_hasher.hash(password))
        self._settings.set_setting(KEY_LOCK_FAIL_COUNT, "0")
        self._settings.set_setting(KEY_LOCK_UNTIL, "0")
        self._kek = derive_kek(password, salt)
        logger.info("Master password set.")

    def try_unlock(self, password: str) -> bool:
        """验证主密码并缓存 KEK；错误计入失败次数，达上限抛 AccountLockedError。"""
        if not self.is_lock_enabled():
            raise VaultError("尚未设置主密码")
        remaining = self.lockout_remaining()
        if remaining > 0:
            raise AccountLockedError(remaining)
        stored = self._settings.get_setting(KEY_MASTER_HASH)
        try:
            _password_hasher.verify(stored, password)
        except VerifyMismatchError:
            self._register_failed_attempt()
            raise UnlockFailedError("密码错误") from None
        except InvalidHashError as e:
            raise VaultError("主密码哈希损坏，无法验证") from e

        self._settings.set_setting(KEY_LOCK_FAIL_COUNT, "0")
        salt = base64.b64decode(self._settings.get_setting(KEY_MASTER_SALT))
        self._kek = derive_kek(password, salt)
        return True

    def verify_password(self, password: str) -> bool:
        """纯校验密码是否正确：不计失败次数、不锁定、不改变会话解锁状态。

        供 LAN Web 服务等外部入口使用；空密码同样走 argon2 校验（留空即通过）。
        """
        if not self.is_lock_enabled():
            return False
        stored = self._settings.get_setting(KEY_MASTER_HASH)
        try:
            _password_hasher.verify(stored, password)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False

    def change_master_password(self, old_password: str, new_password: str) -> int:
        """修改主密码：验证旧密码 → 新盐派生新 KEK → 重 wrap 全部 DEK → 更新哈希。

        返回重 wrap 的条目数。完成后当前会话保持解锁态。
        新密码允许为空（等同取消密码保护，但启动锁界面仍会弹出，留空即可通过）。
        """
        if not self.is_lock_enabled():
            raise VaultError("尚未设置主密码")
        old_kek = self._kek
        if old_kek is None:
            # 会话未解锁：先验证旧密码派生 KEK
            self.try_unlock(old_password)
            old_kek = self._kek
            assert old_kek is not None
        new_salt = secrets.token_bytes(SALT_LEN)
        new_kek = derive_kek(new_password, new_salt)
        rewrapped = self._rewrap_all(old_kek, new_kek)
        self._settings.set_setting(KEY_MASTER_SALT, base64.b64encode(new_salt).decode())
        self._settings.set_setting(KEY_MASTER_HASH, _password_hasher.hash(new_password))
        self._settings.set_setting(KEY_LOCK_FAIL_COUNT, "0")
        self._settings.set_setting(KEY_LOCK_UNTIL, "0")
        self._kek = new_kek
        logger.info("Master password changed, %d items rewrapped.", rewrapped)
        return rewrapped

    def _register_failed_attempt(self) -> None:
        fails = int(self._settings.get_setting(KEY_LOCK_FAIL_COUNT, "0") or 0) + 1
        if fails >= self._max_fail:
            self._settings.set_setting(KEY_LOCK_UNTIL, str(time.time() + self._lockout_seconds))
            self._settings.set_setting(KEY_LOCK_FAIL_COUNT, "0")
            raise AccountLockedError(self._lockout_seconds)
        self._settings.set_setting(KEY_LOCK_FAIL_COUNT, str(fails))

    # ==========================================
    # Vault 加密区
    # ==========================================
    def _require_kek(self) -> bytes:
        if self._kek is None:
            raise VaultLockedError("会话未解锁，请先输入主密码")
        return self._kek

    def encrypt_into_vault(self, src: str) -> int:
        """加密文件入库：AES-GCM 加密 → 临时名原子改名 → send2trash 原文件 → 登记。

        返回 vault_items.id。
        """
        kek = self._require_kek()
        src_path = Path(src)
        if not src_path.is_file():
            raise VaultError(f"文件不存在：{src}")
        data = src_path.read_bytes()

        dek = secrets.token_bytes(DEK_LEN)
        body_nonce, body_ct = _gcm_encrypt(dek, data, _AAD_BODY)
        wrap_nonce, wrapped_dek = _gcm_encrypt(kek, dek, _AAD_DEK)

        self._vault_dir.mkdir(parents=True, exist_ok=True)
        enc_path = self._vault_dir / (uuid.uuid4().hex + ".fmv")
        tmp_path = enc_path.with_suffix(".tmp")
        tmp_path.write_bytes(body_ct)
        os.replace(tmp_path, enc_path)

        item_id = self._vault.add_item(
            str(src_path), str(enc_path), len(body_ct), len(data),
            wrap_nonce + wrapped_dek, body_nonce,
        )
        if item_id < 0:
            enc_path.unlink(missing_ok=True)
            raise VaultError("登记 vault_items 失败")

        try:
            send2trash(str(src_path))
        except Exception as e:
            # 密文已入库但原文件进回收站失败：保留原文件，不视为致命错误
            logger.warning("send2trash failed for %s: %s", src_path, e)
        return item_id

    def decrypt_to_bytes(self, item_id: int) -> bytes:
        """解密条目到内存（预览用）。"""
        kek = self._require_kek()
        item = self._vault.get_item(item_id)
        if item is None:
            raise VaultError("条目不存在")
        enc_file = Path(item.enc_path)
        if not enc_file.is_file():
            raise VaultError("密文文件丢失，无法解密")
        if len(item.wrapped_dek) <= NONCE_LEN:
            raise VaultError("DEK 数据损坏")

        wrap_nonce, wrapped = item.wrapped_dek[:NONCE_LEN], item.wrapped_dek[NONCE_LEN:]
        try:
            dek = _gcm_decrypt(kek, wrap_nonce, wrapped, _AAD_DEK)
            data = _gcm_decrypt(dek, item.nonce, enc_file.read_bytes(), _AAD_BODY)
        except InvalidTag as e:
            raise VaultError("解密失败：密钥不匹配或数据已损坏") from e
        if len(data) != item.orig_size:
            raise VaultError("解密后大小校验失败")
        return data

    def export_plaintext(self, item_id: int, dest_dir: str) -> Path:
        """导出明文到指定目录（重名自动追加序号），返回导出文件路径。"""
        item = self._vault.get_item(item_id)
        if item is None:
            raise VaultError("条目不存在")
        data = self.decrypt_to_bytes(item_id)
        base = Path(item.original_path).name or f"vault_{item_id}"
        dest = Path(dest_dir) / base
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = Path(dest_dir) / f"{stem} ({counter}){suffix}"
            counter += 1
        dest.write_bytes(data)
        logger.info("Vault plaintext exported to %s", dest)
        return dest

    def remove_from_vault(self, item_id: int, *, trash_ciphertext: bool = True) -> None:
        """从库移除条目并删除密文文件（send2trash）。"""
        item = self._vault.get_item(item_id)
        if item is None:
            raise VaultError("条目不存在")
        if not self._vault.delete_item(item_id):
            raise VaultError("删除记录失败")
        enc_file = Path(item.enc_path)
        if enc_file.is_file():
            if trash_ciphertext:
                try:
                    send2trash(str(enc_file))
                except Exception:
                    enc_file.unlink(missing_ok=True)
            else:
                enc_file.unlink(missing_ok=True)

    def get_stats(self) -> tuple[int, int]:
        """（条目数，密文总字节）。"""
        return self._vault.count_items()

    def _rewrap_all(self, old_kek: bytes, new_kek: bytes) -> int:
        """用新 KEK 重 wrap 全部 DEK；任一条目失败即中止（保持原状）。"""
        items = self._vault.list_items()
        rewrapped = 0
        for item in items:
            if len(item.wrapped_dek) <= NONCE_LEN:
                raise VaultError(f"条目 {item.id} DEK 数据损坏，中止修改密码")
            wrap_nonce, wrapped = item.wrapped_dek[:NONCE_LEN], item.wrapped_dek[NONCE_LEN:]
            try:
                dek = _gcm_decrypt(old_kek, wrap_nonce, wrapped, _AAD_DEK)
                new_wrap_nonce, new_wrapped = _gcm_encrypt(new_kek, dek, _AAD_DEK)
            except InvalidTag as e:
                raise VaultError(f"条目 {item.id} 重 wrap 失败，已中止") from e
            if not self._vault.update_wrapped_dek(item.id, new_wrap_nonce + new_wrapped):
                raise VaultError(f"条目 {item.id} 写回失败，已中止")
            rewrapped += 1
        return rewrapped

    # ==========================================
    # 加密备份（Fernet 库快照）
    # ==========================================
    def export_encrypted_backup(self, out_path: str, password: str) -> Path:
        """导出主库的 Fernet 加密快照：magic(8) + salt(16) + token。密码独立于主密码。"""
        if not password:
            raise VaultError("备份密码不能为空")
        db_path = Path(self._db.db_path)
        if not db_path.is_file():
            raise VaultError("数据库文件不存在")

        # sqlite3 backup API 在线一致性复制（兼容 WAL）
        src_conn = sqlite3.connect(str(db_path))
        try:
            fd, tmp_name = tempfile.mkstemp(suffix=".db", prefix="fmbak_")
            os.close(fd)
            tmp = Path(tmp_name)
            dst_conn = sqlite3.connect(str(tmp))
            try:
                with dst_conn:
                    src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        try:
            data = tmp.read_bytes()
        finally:
            tmp.unlink(missing_ok=True)

        salt = secrets.token_bytes(SALT_LEN)
        key = hash_secret_raw(
            password.encode("utf-8"), salt,
            KEK_TIME_COST, KEK_MEMORY_COST, KEK_PARALLELISM, KEK_LEN, Type.ID,
        )
        token = Fernet(base64.urlsafe_b64encode(key)).encrypt(data)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(MAGIC + salt + token)
        logger.info("Encrypted backup written to %s (%d bytes)", out, out.stat().st_size)
        return out

    def restore_encrypted_backup(self, backup_path: str, out_db_path: str, password: str) -> Path:
        """恢复加密备份到指定 db 路径（含 integrity_check 校验）。"""
        raw = Path(backup_path).read_bytes()
        if len(raw) <= len(MAGIC) + SALT_LEN or not raw.startswith(MAGIC):
            raise VaultError("不是有效的 FileMaster 加密备份文件")
        salt = raw[len(MAGIC):len(MAGIC) + SALT_LEN]
        token = raw[len(MAGIC) + SALT_LEN:]
        key = hash_secret_raw(
            password.encode("utf-8"), salt,
            KEK_TIME_COST, KEK_MEMORY_COST, KEK_PARALLELISM, KEK_LEN, Type.ID,
        )
        try:
            data = Fernet(base64.urlsafe_b64encode(key)).decrypt(token)
        except InvalidToken as e:
            raise VaultError("密码错误或备份文件已损坏") from e

        out = Path(out_db_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        conn = sqlite3.connect(str(out))
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if check != "ok":
            out.unlink(missing_ok=True)
            raise VaultError(f"恢复后的数据库完整性校验失败：{check}")
        logger.info("Backup restored to %s", out)
        return out
