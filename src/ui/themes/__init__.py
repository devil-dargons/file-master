# === 文件路径: src/ui/themes/__init__.py ===
"""主题管理：加载 QSS 模板、切换主题、向图标模块提供当前文本色。"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.ui.themes import palette

logger = logging.getLogger(__name__)

THEME_DIR = Path(__file__).parent
_current = palette.DEFAULT_THEME

# 只替换 {color_key} 形式的占位符，避免与 QSS 自身的花括号冲突
_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")


def current_theme() -> str:
    return _current


def load_stylesheet(theme: str) -> str:
    """读取 <theme>.qss 模板并替换颜色占位符。"""
    qss_path = THEME_DIR / f"{theme}.qss"
    if not qss_path.exists():
        qss_path = THEME_DIR / "dark.qss"
        theme = "dark"
    template = qss_path.read_text(encoding="utf-8")
    colors = palette.colors(theme)

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in colors:
            return colors[key]
        logger.warning("QSS 中存在未知颜色占位符: {%s}", key)
        return match.group(0)

    return _TOKEN_RE.sub(_replace, template)


def apply_theme(app: QApplication, theme: str) -> None:
    """切换主题并立即生效（无需重启）。"""
    global _current
    if theme not in palette.THEMES:
        theme = palette.DEFAULT_THEME
    app.setStyleSheet(load_stylesheet(theme))
    _current = theme
    logger.info("Theme applied: %s", theme)


def text_color() -> str:
    return palette.colors(_current)["text"]


def muted_color() -> str:
    return palette.colors(_current)["text_muted"]


def warning_color() -> str:
    return palette.colors(_current)["warning"]
