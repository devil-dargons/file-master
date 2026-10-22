# === 文件路径: src/ui/themes/palette.py ===
"""主题色定义：所有颜色唯一收口处（QSS 与图标颜色均取自此）。"""
from __future__ import annotations

DARK: dict[str, str] = {
    "bg": "#1e1f22",
    "surface": "#26282c",
    "surface_alt": "#2f3237",
    "surface_hover": "#3a3d44",
    "border": "#3a3d42",
    "border_strong": "#4a4e55",
    "text": "#dfe1e5",
    "text_muted": "#9aa0a6",
    "accent": "#4c8dff",
    "accent_hover": "#6aa2ff",
    "accent_pressed": "#3b7ae6",
    "accent_text": "#ffffff",
    "selection": "#2c4a73",
    "selection_text": "#ffffff",
    "danger": "#e5534b",
    "success": "#3fb950",
    "warning": "#d29922",
    "scrollbar": "#4a4e55",
    "scrollbar_hover": "#5c6169",
    "tab_active": "#2f3237",
    "tab_inactive": "#26282c",
}

LIGHT: dict[str, str] = {
    "bg": "#f5f6f8",
    "surface": "#ffffff",
    "surface_alt": "#f0f2f5",
    "surface_hover": "#e8ebef",
    "border": "#dcdfe4",
    "border_strong": "#c4c9d0",
    "text": "#1f2328",
    "text_muted": "#6b7280",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_pressed": "#1e40af",
    "accent_text": "#ffffff",
    "selection": "#dbe8ff",
    "selection_text": "#1f2328",
    "danger": "#d1242f",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "scrollbar": "#c4c9d0",
    "scrollbar_hover": "#a8aeb8",
    "tab_active": "#ffffff",
    "tab_inactive": "#e8ebef",
}

THEMES: dict[str, dict[str, str]] = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"


def colors(theme: str) -> dict[str, str]:
    return THEMES.get(theme, DARK)
