# === 文件路径: tests/conftest.py ===
"""测试夹具：将数据库隔离到临时目录，重置 DatabaseManager 单例。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Qt 测试使用离屏后端，避免依赖真实桌面
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402
from src.db.database import DatabaseManager  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """每个测试独立的 SQLite 文件；结束丢弃。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    DatabaseManager._instance = None  # 重置单例，指向新库
    yield db_path
