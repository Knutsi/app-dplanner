"""The application's main window: a shell around the tab host and its panel areas.

The menu bar's content lives in :mod:`dplanner.framework.menubar`, driven by module-registered
actions; where an anchored panel sits lives in :mod:`dplanner.framework.panels`. This class is
layout and window-level behaviour: the quit-time guards and flush.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.panels import PanelArea, PanelDock
from dplanner.framework.tabs import TabHost
from dplanner.identity import APP_NAME

if TYPE_CHECKING:
    from dplanner.framework.menubar import DynamicMenuBar


class AppWindow(QMainWindow):
    def __init__(self, tabs: TabHost, dock: PanelDock, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setMinimumSize(720, 480)

        # Assigned by the builder; held here so the QMenus outlive construction.
        self.dynamic_menubar: DynamicMenuBar | None = None

        # Run on window close, before teardown — the builder appends the autosave flush, so
        # quitting can never lose the last few seconds of typing.
        self.close_hooks: list[Callable[[], None]] = []
        # Run before close_hooks, in order; a guard returning False cancels the close (the
        # sync module asking "Save before quitting?" when there are uncommitted changes).
        self.close_guards: list[Callable[[], bool]] = []
        self._title_base = APP_NAME

        self.tabs = tabs
        # The window owns no panel slot of its own: every anchored surface is a registered
        # panel, and the dock decides which area it is in.
        self.dock = dock
        self.panels_changed: Signal[str] = dock.panels_changed
        self.areas_changed: Signal[PanelArea] = dock.areas_changed
        self.setCentralWidget(dock)
        self.statusBar().showMessage("Ready")

    # -- status (StatusHost) -----------------------------------------------------------------

    def show_status(self, text: str, msecs: int = 0) -> None:
        self.statusBar().showMessage(text, msecs)

    def add_status_widget(self, widget: QWidget) -> None:
        self.statusBar().addPermanentWidget(widget)

    # -- panels (PanelHost) ------------------------------------------------------------------

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        self.dock.set_panel_visible(panel_id, visible)

    def is_panel_visible(self, panel_id: str) -> bool:
        return self.dock.is_panel_visible(panel_id)

    def set_area_collapsed(self, area: PanelArea, collapsed: bool) -> None:
        self.dock.set_area_collapsed(area, collapsed)

    def is_area_collapsed(self, area: PanelArea) -> bool:
        return self.dock.is_area_collapsed(area)

    # -- unsaved changes (UnsavedChangesHost) -------------------------------------------------

    def set_unsaved(self, unsaved: bool, summary: str = "") -> None:
        if not unsaved:
            self.setWindowTitle(self._title_base)
            return
        detail = f" ({summary})" if summary else ""
        self.setWindowTitle(f"{self._title_base} — Unsaved Changes{detail}")

    def add_close_guard(self, guard: Callable[[], bool]) -> None:
        self.close_guards.append(guard)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        for guard in self.close_guards:
            if not guard():
                event.ignore()
                return
        for hook in self.close_hooks:
            hook()
        super().closeEvent(event)
