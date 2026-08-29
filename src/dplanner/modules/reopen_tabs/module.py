"""Reopen tabs: the window comes back to the work that was open in it.

A tab is identified by its activity URI and by nothing else, which is what makes this safe
to persist. Restoring is `parse_activity_uri` followed by the same `tabs.open(kind, target)`
call a menu item makes — so a remembered tab is reopened by the one path that opens
anything, and no surface grows a second, restore-only way in.

**Everything that can be stale is checked, and a stale entry simply does not reappear.**
Three things can have changed since the list was written: the *kind* may be gone from this
build (`tabs.can_open`), the *target* may be gone from the library (the `exists` callback —
the composition root hands over `Library.has`, so this module never learns what a project
is), and the factory may refuse for a reason neither test could see, which is caught and
logged. A window that opens with fewer tabs than it had is the correct degradation; one
that refuses to start is not, and that is why the last guard is deliberately broad.

The list is per library — a tab list is only true of the library it was written in — while
the on/off preference is per user. :mod:`dplanner.framework.user_config` has the two scopes
and why they are different.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from dplanner.framework.context import parse_activity_uri
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.user_config import get_scoped, set_scoped
from dplanner.modules.reopen_tabs.settings_page import MODULE_ID, build_page, reopen_wanted

logger = logging.getLogger(__name__)

OPEN_KEY = "open_tabs"


@dataclass(frozen=True)
class ReopenTabsDeps:
    tabs: TabHost
    settings_sections: SettingsSectionRegistry
    # This library's slice of the per-user store, from the composition root.
    scope: str
    # Is an activity's target still in the model? A remembered tab naming something that
    # has been deleted is dropped rather than opened onto nothing.
    exists: Callable[[str], bool]


class ReopenTabsModule:
    id = MODULE_ID

    def __init__(self, deps: ReopenTabsDeps) -> None:
        self._deps = deps
        # Reopening opens tabs, and opening a tab is what triggers a save.
        self._restoring = False

    def register(self) -> None:
        deps = self._deps
        deps.settings_sections.register(
            SettingsSection(id=f"{MODULE_ID}.startup", category=("Startup",), factory=build_page)
        )
        # Connected before the reopen, so what keeps the two from fighting is the
        # ``_restoring`` guard rather than the order of these three lines.
        deps.tabs.tabs_changed.connect(self._remember)
        deps.tabs.activity_changed.connect(lambda _activity: self._remember())
        if reopen_wanted():
            self._reopen()

    # -- remembering ---------------------------------------------------------------------------

    def _remember(self) -> None:
        """Write the tab list down on every change, rather than at close.

        Two things make that the cheaper answer. A library reload builds the new window
        *before* the old one is closed, so a list written at close time would be written
        after the window that was going to read it — the tabs would come back one session
        stale. And a crash is exactly the moment somebody wants their tabs back.

        Written whatever the preference says: the setting governs *reopening*, so turning
        it back on gives the user the session they last had rather than one from whenever
        they turned it off.
        """
        if self._restoring:
            return
        tabs = self._deps.tabs
        current = tabs.current_activity()
        set_scoped(
            self._deps.scope,
            MODULE_ID,
            OPEN_KEY,
            {
                # Tab order, across every pane. Panes themselves are not restored: a split
                # is an arrangement of the window, and reopening into one pane is honest
                # about what is being remembered.
                "open": [activity.uri for activity in tabs.activities()],
                "current": current.uri if current is not None else "",
            },
        )

    # -- reopening -----------------------------------------------------------------------------

    def _reopen(self) -> None:
        stored = get_scoped(self._deps.scope, MODULE_ID, OPEN_KEY, {})
        if not isinstance(stored, dict):
            return  # Written by something that is not this; there is nothing to restore.
        open_uris = stored.get("open")
        current = stored.get("current")
        self._restoring = True
        try:
            for uri in open_uris if isinstance(open_uris, list) else []:
                self._open(uri)
            # Opening it again is a plain focus, so the tab the user was on is current
            # without this module knowing anything about how focus works.
            if isinstance(current, str):
                self._open(current)
        finally:
            self._restoring = False

    def _open(self, uri: object) -> None:
        parsed = parse_activity_uri(uri) if isinstance(uri, str) else None
        if parsed is None:
            return
        kind, target = parsed
        if not self._deps.tabs.can_open(kind):
            return  # A feature this build no longer has.
        if target is not None and not self._deps.exists(target):
            return  # The project it was showing is gone.
        try:
            self._deps.tabs.open(kind, target)
        except Exception:
            # Deliberately broad: a surface that cannot rebuild itself must cost the user
            # one tab, never the launch.
            logger.warning("could not reopen %s", uri, exc_info=True)
