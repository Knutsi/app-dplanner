"""The window sidebar as a small tab set, fed by registries.

A :class:`SidebarShell` — a flat tab bar over a stack — whose pages come from a
:class:`SidebarPanelRegistry`, so any module can contribute a panel without the shell
learning who exists. The window installs the shell exactly once and never finds out what it
will hold.

The "Utility" page is itself an extension area, one level down: modules register a
:class:`UtilityTool` widget and :class:`UtilityPanel` stacks them in order. Two levels are
enough — a feature that wants the whole panel takes a page, one that is a small block among
others takes a utility slot.

Registration happens only during startup, so the shell keeps the lowest-order page current
and never has to arbitrate with a user's click.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QStackedLayout, QTabBar, QVBoxLayout, QWidget

from dplanner.core.signals import Signal


@dataclass(frozen=True)
class SidebarPanel:
    id: str  # "explorer", "utility" — globally unique.
    label: str  # Tab text.
    widget: QWidget
    order: int = 50  # Tab position; lowest order is the startup page.
    # Tab glyph, colour-parameterized like everything in dplanner.theme.icons; the shell's
    # owner feeds it the theme's secondary text colour and re-feeds on theme change.
    icon: Callable[[str], QIcon] | None = None


class SidebarPanelRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, SidebarPanel] = {}
        self.registered: Signal[SidebarPanel] = Signal()
        self.select_requested: Signal[str] = Signal()

    def register(self, panel: SidebarPanel) -> None:
        if panel.id in self._panels:
            raise ValueError(f"sidebar panel {panel.id!r} already registered")
        self._panels[panel.id] = panel
        self.registered.emit(panel)

    def panels(self) -> list[SidebarPanel]:
        return sorted(self._panels.values(), key=lambda p: (p.order, p.id))

    def select(self, panel_id: str) -> None:
        """Ask the shell to bring ``panel_id``'s page to the front."""
        self.select_requested.emit(panel_id)


class SidebarShell(QWidget):
    """The one widget installed via ``SidebarHost.set_sidebar``: tabs over a stack."""

    def __init__(self, panels: SidebarPanelRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarShell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._ids: list[str] = []
        self._orders: list[tuple[int, str]] = []
        self._panels: list[SidebarPanel] = []
        self._icon_color = ""

        self._tab_bar = QTabBar()
        self._tab_bar.setObjectName("SidebarTabs")
        self._tab_bar.setExpanding(False)
        self._tab_bar.setDrawBase(False)
        self._stack = QStackedLayout()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tab_bar)
        layout.addLayout(self._stack)

        self._tab_bar.currentChanged.connect(self._stack.setCurrentIndex)
        for panel in panels.panels():
            self._add_panel(panel)
        panels.registered.connect(self._add_panel)
        panels.select_requested.connect(self._select)

    def current_panel_id(self) -> str | None:
        index = self._tab_bar.currentIndex()
        return self._ids[index] if 0 <= index < len(self._ids) else None

    def set_icon_color(self, color: str) -> None:
        """Repaint every tab glyph — called on install and on each theme change."""
        self._icon_color = color
        for index, panel in enumerate(self._panels):
            if panel.icon is not None:
                self._tab_bar.setTabIcon(index, panel.icon(color))

    def _add_panel(self, panel: SidebarPanel) -> None:
        key = (panel.order, panel.id)
        index = len([k for k in self._orders if k <= key])
        self._orders.insert(index, key)
        self._ids.insert(index, panel.id)
        self._panels.insert(index, panel)
        self._stack.insertWidget(index, panel.widget)
        self._tab_bar.insertTab(index, panel.label)
        if panel.icon is not None and self._icon_color:
            self._tab_bar.setTabIcon(index, panel.icon(self._icon_color))
        # Registration only happens during startup: the lowest-order page wins.
        self._tab_bar.setCurrentIndex(0)
        self._stack.setCurrentIndex(0)

    def _select(self, panel_id: str) -> None:
        if panel_id in self._ids:
            self._tab_bar.setCurrentIndex(self._ids.index(panel_id))


@dataclass(frozen=True)
class UtilityTool:
    id: str  # Module-prefixed, globally unique.
    widget: QWidget
    order: int = 50


class UtilityToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, UtilityTool] = {}
        self.registered: Signal[UtilityTool] = Signal()

    def register(self, tool: UtilityTool) -> None:
        if tool.id in self._tools:
            raise ValueError(f"utility tool {tool.id!r} already registered")
        self._tools[tool.id] = tool
        self.registered.emit(tool)

    def tools(self) -> list[UtilityTool]:
        return sorted(self._tools.values(), key=lambda t: (t.order, t.id))


class UtilityPanel(QWidget):
    """The "Utility" sidebar page: registered tool widgets stacked top to bottom."""

    def __init__(self, tools: UtilityToolRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UtilityPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._orders: list[tuple[int, str]] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)

        for tool in tools.tools():
            self._add_tool(tool)
        tools.registered.connect(self._add_tool)

    def _add_tool(self, tool: UtilityTool) -> None:
        key = (tool.order, tool.id)
        index = len([k for k in self._orders if k <= key])
        self._orders.insert(index, key)
        # The trailing stretch stays last because every insert lands before it.
        self._layout.insertWidget(index, tool.widget)
