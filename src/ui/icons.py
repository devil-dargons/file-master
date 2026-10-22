# === 文件路径: src/ui/icons.py ===
"""图标服务：qtawesome 矢量图标，颜色跟随主题；缺库时降级为空图标。"""
from __future__ import annotations

import logging

from PySide6.QtGui import QIcon

from src.ui import themes

logger = logging.getLogger(__name__)

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:  # pragma: no cover - 环境缺失时降级
    qta = None
    HAS_QTAWESOME = False
    logger.warning("qtawesome 未安装，界面将不显示图标")

_cache: dict[tuple[str, str], QIcon] = {}


def get_icon(name: str, color: str | None = None) -> QIcon:
    """按 (图标名, 颜色) 缓存图标；颜色默认取当前主题正文色。"""
    if not HAS_QTAWESOME:
        return QIcon()

    color = color or themes.text_color()
    key = (name, color)
    icon = _cache.get(key)
    if icon is None:
        try:
            icon = qta.icon(name, color=color)
        except Exception:
            logger.warning("Unknown icon: %s", name)
            icon = QIcon()
        _cache[key] = icon
    return icon


def refresh() -> None:
    """主题切换后清空缓存，使图标按新主题颜色重绘。"""
    _cache.clear()
