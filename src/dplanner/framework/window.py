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


class StatusHost(Protocol):
    """Transient status messages and permanent status-bar widgets."""

    def show_status(self, text: str, msecs: int = 0) -> None: ...

    def add_status_widget(self, widget: QWidget) -> None: ...


class SidebarHost(Protocol):
    """The window's single sidebar slot: whichever module installs a widget owns it."""

    def set_sidebar(self, widget: QWidget) -> None: ...

    def set_sidebar_visible(self, visible: bool) -> None: ...

    def is_sidebar_visible(self) -> bool: ...

    def reset_sidebar_width(self) -> None: ...


class ImmersiveHost(Protocol):
    """Distraction-free mode: full screen without chrome."""

    immersive_changed: Signal[bool]

    def enter_immersive(self) -> None: ...

    def leave_immersive(self) -> None: ...

    def is_immersive(self) -> bool: ...


class UnsavedChangesHost(Protocol):
    """Window chrome for "you have unsaved changes": the headline flag and a veto on quit.

    A guard runs at close time and returns whether the close may proceed — the one it
    needs (gitsync) uses this to ask "Save before quitting?" instead of losing the
    decision silently.
    """

    def set_unsaved(self, unsaved: bool, summary: str = "") -> None: ...

    def add_close_guard(self, guard: Callable[[], bool]) -> None: ...
