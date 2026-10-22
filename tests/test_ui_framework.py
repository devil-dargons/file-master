# === 文件路径: tests/test_ui_framework.py ===
"""M1 界面框架冒烟：注册表、面板基类、主题、主窗口布局与持久化。"""
from __future__ import annotations

from PySide6.QtWidgets import QDockWidget, QWidget

from src.ui import themes
from src.ui.framework.panel_base import PanelBase
from src.ui.framework.registry import PANEL_REGISTRY, iter_specs


def test_registry_specs_are_complete():
    assert set(PANEL_REGISTRY) == {
        "directory_tree", "file_tags", "query_builder", "detail", "duplicates", "task_output",
    }
    for spec in iter_specs():
        assert spec.panel_id == spec.panel_id.strip()
        assert spec.title and spec.menu_text
        assert callable(spec.factory)


def test_panel_base_dock_capabilities(qapp):
    panel = PanelBase("probe", "探针面板", QWidget())
    assert panel.objectName() == "panel_probe"

    features = QDockWidget.DockWidgetFeatures(panel.features())
    assert features & QDockWidget.DockWidgetFloatable
    assert features & QDockWidget.DockWidgetMovable
    assert features & QDockWidget.DockWidgetClosable

    # 钉住后不可浮动/关闭
    panel.set_pinned(True)
    assert panel.features() == QDockWidget.NoDockWidgetFeatures
    panel.set_pinned(False)
    assert panel.features() & QDockWidget.DockWidgetMovable


def test_themes_render_without_placeholders(qapp):
    for name in ("dark", "light"):
        qss = themes.load_stylesheet(name)
        assert "background-color:" in qss
        assert "{" not in qss.split("QDockWidget")[0].split("QWidget")[0]  # 占位符已全部替换


def test_main_window_layout_and_persistence(temp_db, qapp):
    from src.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()

    assert set(win._panels) == set(PANEL_REGISTRY)
    assert win.centralWidget() is win.central_panel

    # 面板可关闭，并能从“视图”菜单（toggleViewAction）找回
    detail = win._panels["detail"]
    detail.close()
    qapp.processEvents()
    assert not detail.isVisible()
    detail.toggleViewAction().trigger()
    qapp.processEvents()
    assert detail.isVisible()

    # 可浮动为独立窗口
    detail.setFloating(True)
    qapp.processEvents()
    assert detail.isFloating()
    detail.setFloating(False)

    # 主题切换即时生效
    win._set_theme("light")
    assert win._theme == "light"
    assert win.settings_dao.get_setting("theme") == "light"

    win.close()
    qapp.processEvents()

    assert win.settings_dao.get_setting("layout_state")
    assert win.settings_dao.get_setting("window_geometry")
