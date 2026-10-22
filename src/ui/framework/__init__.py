# === 文件路径: src/ui/framework/__init__.py ===
from src.ui.framework.panel_base import PanelBase
from src.ui.framework.registry import PANEL_REGISTRY, PanelContext, PanelSpec

__all__ = ["PanelBase", "PANEL_REGISTRY", "PanelContext", "PanelSpec"]
