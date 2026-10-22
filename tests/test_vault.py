# === 文件路径: tests/test_vault.py ===
"""M4 安全回环测试（开发手册 5.6 / 七-测试）：

- 启动锁：设置 / 验证 / 连续错误锁定与解除
- Vault 回环：加密入库 → 解密字节一致；错密钥失败；改主密码重 wrap 后可解
- 加密备份：导出 → 恢复字节一致；错密码失败
"""
from __future__ import annotations

import base64
import sqlite3

import pytest

from src.core.vault import (
    AccountLockedError, UnlockFailedError, VaultError, VaultLockedError, VaultService,
)
from src.db.dao import SettingsDAO, VaultDAO
from src.db.database import DatabaseManager


@pytest.fixture
def service(tmp_path, temp_db, monkeypatch):
    """VaultService 实例（max_fail=3 / 锁定 1 秒，便于测试锁定逻辑）。

    send2trash 替换为记录器，避免测试污染系统回收站。
    """
    sent: list[str] = []
    monkeypatch.setattr("src.core.vault.send2trash", lambda p: sent.append(str(p)))
    db = DatabaseManager()
    svc = VaultService(db, SettingsDAO(db), VaultDAO(db), tmp_path / "vault",
                       max_fail=3, lockout_seconds=5)
    svc.sent_to_trash = sent  # 供断言
    return svc


@pytest.fixture
def unlocked(service):
    service.set_master_password("correct-horse")
    return service


def _make_file(tmp_path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ==========================================
# 启动锁
# ==========================================
def test_password_set_and_verify(service):
    assert not service.is_lock_enabled()
    service.set_master_password("pw123")
    assert service.is_lock_enabled()
    assert service.is_unlocked()
    # 新会话（KEK 缓存清空）验证
    service.lock()
    assert not service.is_unlocked()
    assert service.try_unlock("pw123") is True
    service.lock()
    with pytest.raises(UnlockFailedError):
        service.try_unlock("wrong")


def test_lockout_after_max_failures(service):
    service.set_master_password("pw123")
    service.lock()
    for _ in range(2):
        with pytest.raises(UnlockFailedError):
            service.try_unlock("bad")
    with pytest.raises(AccountLockedError) as exc:
        service.try_unlock("bad")
    assert 0 < exc.value.remaining_seconds <= 5
    assert service.lockout_remaining() > 0
    # 锁定期间即使密码正确也拒绝
    with pytest.raises(AccountLockedError):
        service.try_unlock("pw123")


def test_change_password_requires_old_password(service):
    service.set_master_password("old-pw")
    service.lock()
    with pytest.raises(UnlockFailedError):
        service.change_master_password("not-old", "new-pw")


# ==========================================
# Vault 加密回环
# ==========================================
def test_encrypt_decrypt_roundtrip(unlocked, tmp_path):
    payload = b"secret-content-" + bytes(range(256)) * 4
    src = _make_file(tmp_path, "secret.bin", payload)

    item_id = unlocked.encrypt_into_vault(src)

    assert item_id > 0
    # 原文件已进回收站（测试中为记录器）
    assert unlocked.sent_to_trash and unlocked.sent_to_trash[0].endswith("secret.bin")
    # 密文文件存在且不含明文片段
    items = unlocked._vault.list_items()
    assert len(items) == 1
    assert items[0].orig_size == len(payload)
    enc_file = items[0].enc_path
    with open(enc_file, "rb") as f:
        assert payload not in f.read()
    # 解密字节一致
    assert unlocked.decrypt_to_bytes(item_id) == payload


def test_decrypt_without_unlock_raises(service, tmp_path):
    service.set_master_password("pw")
    src = _make_file(tmp_path, "a.bin", b"data")
    item_id = service.encrypt_into_vault(src)
    service.lock()
    with pytest.raises(VaultLockedError):
        service.decrypt_to_bytes(item_id)
    with pytest.raises(VaultLockedError):
        service.encrypt_into_vault(src)


def test_rewrap_after_password_change(unlocked, tmp_path):
    payloads = {
        unlocked.encrypt_into_vault(_make_file(tmp_path, "f1.bin", b"one" * 100)): b"one" * 100,
        unlocked.encrypt_into_vault(_make_file(tmp_path, "f2.bin", b"two" * 200)): b"two" * 200,
    }
    n = unlocked.change_master_password("correct-horse", "new-pw-456")
    assert n == 2
    # 新密码可解锁且数据完好；旧密码被拒
    assert unlocked.is_unlocked()
    for item_id, payload in payloads.items():
        assert unlocked.decrypt_to_bytes(item_id) == payload
    unlocked.lock()
    with pytest.raises(UnlockFailedError):
        unlocked.try_unlock("correct-horse")
    assert unlocked.try_unlock("new-pw-456") is True


def test_export_plaintext_and_remove(unlocked, tmp_path):
    payload = b"export-me"
    item_id = unlocked.encrypt_into_vault(_make_file(tmp_path, "doc.txt", payload))
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    dest = unlocked.export_plaintext(item_id, str(dest_dir))
    assert dest.name == "doc.txt"
    assert dest.read_bytes() == payload
    # 移除：记录与密文都消失
    unlocked.remove_from_vault(item_id)
    assert unlocked._vault.get_item(item_id) is None
    items = unlocked._vault.list_items()
    assert not items


def test_encrypt_missing_file_raises(unlocked, tmp_path):
    with pytest.raises(VaultError):
        unlocked.encrypt_into_vault(str(tmp_path / "not-exist.bin"))


# ==========================================
# 加密备份
# ==========================================
def test_encrypted_backup_roundtrip(unlocked, tmp_path):
    # 先造点数据进库
    src = _make_file(tmp_path, "seed.bin", b"seed")
    unlocked.encrypt_into_vault(src)

    backup = tmp_path / "backup.fmbackup"
    unlocked.export_encrypted_backup(str(backup), "backup-pass")

    raw = backup.read_bytes()
    assert raw[:7] == b"FMBAK01"
    assert len(raw) > 7 + 16

    out_db = tmp_path / "restored.db"
    unlocked.restore_encrypted_backup(str(backup), str(out_db), "backup-pass")
    assert out_db.is_file()
    # 恢复出的库可打开且 vault_items 行数一致
    conn = sqlite3.connect(str(out_db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM vault_items").fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_encrypted_backup_wrong_password(unlocked, tmp_path):
    backup = tmp_path / "b.fmbackup"
    unlocked.export_encrypted_backup(str(backup), "right-pass")
    with pytest.raises(VaultError):
        unlocked.restore_encrypted_backup(str(backup), str(tmp_path / "x.db"), "wrong-pass")
    # 损坏 magic 头也要拒绝
    backup.write_bytes(b"NOTMAGIC" + backup.read_bytes()[8:])
    with pytest.raises(VaultError):
        unlocked.restore_encrypted_backup(str(backup), str(tmp_path / "x.db"), "right-pass")


def test_kek_is_password_derived(unlocked, tmp_path):
    """同库不同密码派生的 KEK 不能解开密文（防直接换服务对象绕过）。"""
    payload = b"locked-tight"
    item_id = unlocked.encrypt_into_vault(_make_file(tmp_path, "k.bin", payload))
    # 模拟"丢失主密码后用新密码重新派生"——未重 wrap，解密必须失败
    from src.core.vault import derive_kek, KEY_MASTER_SALT
    salt = base64.b64decode(unlocked._settings.get_setting(KEY_MASTER_SALT))
    rogue = VaultService(
        unlocked._db, unlocked._settings, unlocked._vault, unlocked._vault_dir)
    rogue._kek = derive_kek("totally-different", salt)
    with pytest.raises(VaultError):
        rogue.decrypt_to_bytes(item_id)
