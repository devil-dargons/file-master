# === 文件路径: src/ui/framework/panel_base.py ===
"""可停靠面板基类：统一标题栏 + 浮动/钉住/最大化/关闭。

布局持久化依赖 objectName，所有子类必须传唯一 panel_id。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QLabel, QToolButton, QWidget,
)

from src.ui.icons import get_icon


class _PanelTitleBar(QWidget):
    """自定义标题栏：标题 + 四个操作按钮，双击标题切换浮动。"""

    def __init__(self, dock: "PanelBase", title: str):
        super().__init__(dock)
        self.setObjectName("panelTitleBar")
        self._dock = dock
        self._maximized = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(2)

        self.label = QLabel(title, self)
        self.label.setObjectName("panelTitleLabel")
        layout.addWidget(self.label, 1)

        self.btn_float = self._make_button("fa5s.window-restore", "浮动为独立窗口")
        self.btn_pin = self._make_button("fa5s.thumbtack", "钉住（锁定面板位置）", checkable=True)
        self.btn_max = self._make_button("fa5s.expand", "最大化 / 还原")
        self.btn_close = self._make_button("fa5s.times", "关闭面板")

        layout.addWidget(self.btn_float)
        layout.addWidget(self.btn_pin)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

        self.btn_float.clicked.connect(self._toggle_floating)
        self.btn_pin.toggled.connect(self._toggle_pin)
        self.btn_max.clicked.connect(self._toggle_maximized)
        self.btn_close.clicked.connect(dock.close)

    def _make_button(self, icon_name: str, tip: str, checkable: bool = False) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("panelTitleButton")
        btn.setIcon(get_icon(icon_name))
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    # ---- 交互 ----
    def _toggle_floating(self) -> None:
        self._dock.setFloating(not self._dock.isFloating())

    def _toggle_pin(self, pinned: bool) -> None:
        self._dock.set_pinned(pinned)

    def _toggle_maximized(self) -> None:
        self._dock.toggle_maximized()
        self._maximized = not self._maximized
        self.btn_max.setIcon(get_icon("fa5s.compress" if self._maximized else "fa5s.expand"))

    def mouseDoubleClickEvent(self, event: QEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_floating()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def refresh_icons(self) -> None:
        self.btn_float.setIcon(get_icon("fa5s.window-restore"))
        self.btn_pin.setIcon(get_icon("fa5s.thumbtack"))
        self.btn_max.setIcon(get_icon("fa5s.compress" if self._maximized else "fa5s.expand"))
        self.btn_close.setIcon(get_icon("fa5s.times"))


class PanelBase(QDockWidget):
    """所有功能面板的基类。"""

    closed_by_user = Signal(str)   # panel_id

    def __init__(self, panel_id: str, title: str, content: QWidget | None = None, parent=None):
        super().__init__(title, parent)
        self.panel_id = panel_id
        self.setObjectName(f"panel_{panel_id}")
        self.setWindowTitle(title)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )

        if content is not None:
            self.setWidget(content)

        self._title_bar = _PanelTitleBar(self, title)
        self.setTitleBarWidget(self._title_bar)

    # ---- 状态 ----
    @property
    def pinned(self) -> bool:
        return self._title_bar.btn_pin.isChecked()

    def set_pinned(self, pinned: bool) -> None:
        """钉住：锁定位置，禁止拖动/浮动/关闭。"""
        self.setFeatures(
            QDockWidget.NoDockWidgetFeatures if pinned
            else QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self._title_bar.btn_float.setEnabled(not pinned)
        self._title_bar.btn_close.setEnabled(not pinned)
        if pinned:
            self.setFloating(False)

    def toggle_maximized(self) -> None:
        if not self.isFloating():
            self.setFloating(True)
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def refresh_icons(self) -> None:
        self._title_bar.refresh_icons()

    def closeEvent(self, event) -> None:
        self.closed_by_user.emit(self.panel_id)
        super().closeEvent(event)
