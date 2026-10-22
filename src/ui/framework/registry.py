# === 文件路径: src/ui/framework/registry.py ===
"""面板注册表：新增功能面板 = 写一个类 + 在这里注册一行，主窗口零改动。

PANEL_REGISTRY: panel_id -> PanelSpec(工厂, 默认停靠区, 菜单文案, 图标, 快捷键, 页签组)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from src.core.file_service import FileService
from src.db.database import DatabaseManager
from src.ui.panels.detail_panel import DetailPanel
from src.ui.panels.directory_tree_panel import DirectoryTreePanel
from src.ui.panels.duplicate_panel import DuplicatePanel
from src.ui.panels.query_builder_panel import QueryBuilderPanel
from src.ui.panels.tag_panel import TagPanel
from src.ui.panels.task_output_panel import TaskOutputPanel


@dataclass
class PanelContext:
    """面板工厂可用的依赖集合（避免面板直接 import 全局单例）。"""

    db_manager: DatabaseManager
    file_service: FileService


@dataclass(frozen=True)
class PanelSpec:
    panel_id: str
    title: str
    menu_text: str
    area: int
    factory: Callable[[PanelContext], QWidget]
    icon: str = "fa5s.square"
    shortcut: str | None = None
    tab_group: str | None = None          # 同组面板自动 tabify


def _build_directory_tree(ctx: PanelContext) -> QWidget:
    return DirectoryTreePanel()


def _build_file_tags(ctx: PanelContext) -> QWidget:
    return TagPanel(ctx.db_manager, ctx.file_service)


def _build_query_builder(ctx: PanelContext) -> QWidget:
    return QueryBuilderPanel(ctx.db_manager)


def _build_detail(ctx: PanelContext) -> QWidget:
    return DetailPanel()


def _build_duplicates(ctx: PanelContext) -> QWidget:
    return DuplicatePanel(ctx.db_manager, ctx.file_service)


def _build_task_output(ctx: PanelContext) -> QWidget:
    return TaskOutputPanel()


PANEL_REGISTRY: dict[str, PanelSpec] = {
    "directory_tree": PanelSpec(
        panel_id="directory_tree", title="目录树", menu_text="目录树",
        area=Qt.LeftDockWidgetArea, factory=_build_directory_tree,
        icon="fa5s.sitemap", shortcut="Ctrl+1",
    ),
    "file_tags": PanelSpec(
        panel_id="file_tags", title="标签", menu_text="标签",
        area=Qt.RightDockWidgetArea, factory=_build_file_tags,
        icon="fa5s.tags", shortcut="Ctrl+2", tab_group="right",
    ),
    "query_builder": PanelSpec(
        panel_id="query_builder", title="条件构造器", menu_text="条件构造器",
        area=Qt.RightDockWidgetArea, factory=_build_query_builder,
        icon="fa5s.filter", shortcut="Ctrl+6", tab_group="right",
    ),
    "detail": PanelSpec(
        panel_id="detail", title="详情预览", menu_text="详情预览",
        area=Qt.RightDockWidgetArea, factory=_build_detail,
        icon="fa5s.info-circle", shortcut="Ctrl+3", tab_group="right",
    ),
    "duplicates": PanelSpec(
        panel_id="duplicates", title="重复文件", menu_text="重复文件",
        area=Qt.BottomDockWidgetArea, factory=_build_duplicates,
        icon="fa5s.copy", shortcut="Ctrl+4", tab_group="bottom",
    ),
    "task_output": PanelSpec(
        panel_id="task_output", title="任务输出", menu_text="任务输出",
        area=Qt.BottomDockWidgetArea, factory=_build_task_output,
        icon="fa5s.terminal", shortcut="Ctrl+5", tab_group="bottom",
    ),
}


def iter_specs() -> list[PanelSpec]:
    return list(PANEL_REGISTRY.values())
