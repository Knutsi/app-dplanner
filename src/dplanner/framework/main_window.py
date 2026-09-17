"""The application's main window: a shell around the tab host and its panel areas.

The menu bar's content lives in :mod:`dplanner.framework.menubar`, driven by module-registered
actions; where an anchored panel sits lives in :mod:`dplanner.framework.panels`. This class is
layout and window-level behaviour: the quit-time guards and flush.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.notices import Notice, NoticeBar
from dplanner.framework.panels import PanelArea, PanelDock
from dplanner.framework.tabs import TabHost
from dplanner.identity import APP_NAME

if TYPE_CHECKING:
    from dplanner.framework.menubar import DynamicMenuBar

# One window-level fact in the bare per-user store, like the theme and the zoom.
GEOMETRY_KEY = "window/geometry"


class AppWindow(QMainWindow):
    def __init__(self, tabs: TabHost, dock: PanelDock, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setMinimumSize(720, 480)
        # Where the last window was left; the size above is only the first launch's.
        remembered = QSettings().value(GEOMETRY_KEY)
        if isinstance(remembered, QByteArray) and not remembered.isEmpty():
            self.restoreGeometry(remembered)

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
        # Standing notices sit over the content, not in the status bar: a fact that holds
        # while the person works has to be where they are working. The bar is invisible
        # while nothing stands, so an ordinary window is exactly as it was.
        self.notices = NoticeBar(self)
        content = QWidget(self)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.notices)
        column.addWidget(dock, 1)
        self.setCentralWidget(content)
        self.statusBar().showMessage("Ready")

    # -- status (StatusHost) -----------------------------------------------------------------

    def show_status(self, text: str, msecs: int = 0) -> None:
        self.statusBar().showMessage(text, msecs)

    def add_status_widget(self, widget: QWidget) -> None:
        self.statusBar().addPermanentWidget(widget)

    # -- standing notices (NoticeHost) --------------------------------------------------------

    def show_notice(self, notice: Notice) -> None:
        self.notices.show_notice(notice)

    def clear_notice(self, notice_id: str) -> None:
        self.notices.clear_notice(notice_id)

    # -- panels (PanelHost) ------------------------------------------------------------------

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        self.dock.set_panel_visible(panel_id, visible)

    def is_panel_visible(self, panel_id: str) -> bool:
        return self.dock.is_panel_visible(panel_id)

    def set_area_collapsed(self, area: PanelArea, collapsed: bool) -> None:
        self.dock.set_area_collapsed(area, collapsed)

    def is_area_collapsed(self, area: PanelArea) -> bool:
        return self.dock.is_area_collapsed(area)

    def area_of(self, panel_id: str) -> PanelArea | None:
        return self.dock.area_of(panel_id)

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
        QSettings().setValue(GEOMETRY_KEY, self.saveGeometry())
        super().closeEvent(event)
