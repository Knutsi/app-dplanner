"""Window capabilities, as narrow protocols.

Modules never need the whole :class:`dplanner.framework.main_window.AppWindow` — they need one of
the small surfaces below. Depending on a protocol keeps the dependency honest (a module
that shows status messages cannot quietly start toggling full screen) and lets tests pass
a trivial fake. ``AppWindow`` satisfies all of them structurally.
"""

from collections.abc import Callable
from typing import Protocol

from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal
from dplanner.framework.panels import PanelArea


class StatusHost(Protocol):
    """Transient status messages and permanent status-bar widgets."""

    def show_status(self, text: str, msecs: int = 0) -> None: ...

    def add_status_widget(self, widget: QWidget) -> None: ...


class MenuCornerHost(Protocol):
    """The menu bar's top-right corner: one small widget that reads as chrome.

    A single slot by Qt's construction, so the module that fills it owns it — the notices
    bell today. It is not a second status bar: the status bar says what is happening now,
    the corner what is waiting for the user when they have time.
    """

    def set_menu_corner_widget(self, widget: QWidget) -> None: ...


class PanelHost(Protocol):
    """Which of the window's anchored panels the user has switched on.

    Where a panel sits, and whether it currently has anything to show, are the dock's own
    business (:mod:`dplanner.framework.panels`) — this is only the user's on/off, which is what
    a View menu needs. ``panels_changed`` carries the panel id, and exists because that
    on/off can also be flipped from a panel's own header menu. An area collapse is the same
    kind of fact one level up — a whole side switched off at once — so it lives here too, and
    ``areas_changed`` exists because collapse also flips when a gesture reveals a panel.
    """

    panels_changed: Signal[str]
    areas_changed: Signal[PanelArea]

    def set_panel_visible(self, panel_id: str, visible: bool) -> None: ...

    def is_panel_visible(self, panel_id: str) -> bool: ...

    def set_area_collapsed(self, area: PanelArea, collapsed: bool) -> None: ...

    def is_area_collapsed(self, area: PanelArea) -> bool: ...


class UnsavedChangesHost(Protocol):
    """Window chrome for "you have unsaved changes": the headline flag and a veto on quit.

    A guard runs at close time and returns whether the close may proceed — the one it
    needs (gitsync) uses this to ask "Save before quitting?" instead of losing the
    decision silently.
    """

    def set_unsaved(self, unsaved: bool, summary: str = "") -> None: ...

    def add_close_guard(self, guard: Callable[[], bool]) -> None: ...
