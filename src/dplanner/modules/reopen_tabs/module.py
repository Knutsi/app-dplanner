"""Reopen tabs: the window comes back to the work that was open in it, and remembers what
was kept lately.

A tab is identified by its activity URI and by nothing else, which is what makes this safe
to persist. Restoring is ``tabs.reopen(uri, exists)`` — `TabHost` parses the address and hands
it to the same ``open(kind, target)`` a menu item calls, so a remembered tab is reopened by
the one path that opens anything, and no surface grows a second, restore-only way in.

**Everything that can be stale is checked, and a stale entry simply does not reappear.**
The kind may be gone from this build, the target from the library (the `exists` callback —
the composition root hands over `Library.has`, so this module never learns what a project
is), and the factory may refuse for a reason neither test could see. `TabHost.reopen` asks
all three, because Home's recent list asks the same questions of the same addresses.

**The recent tabs are kept here, beside the open ones**, though Home is what lists them. A
tab is recent when the person *kept* it — made it current, and not as a preview — and this
module is the one that can tell that from a reopen: it does the reopening, behind the
``_restoring`` guard, so the tabs it brings back are not taken for the person's choice.

Both lists are per library — a tab list is only true of the library it was written in —
while the on/off preference is per user. :mod:`dplanner.framework.user_config` has the two
scopes and why they are different.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from dplanner.core.signals import Signal
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tabs import KeptTab, TabHost
from dplanner.framework.user_config import get_scoped, set_scoped
from dplanner.modules.reopen_tabs.settings_page import MODULE_ID, build_page, reopen_wanted

OPEN_KEY = "open_tabs"
RECENT_KEY = "recent_tabs"
# About as many as a person scans without searching; the rest were not really recent.
RECENT_CAP = 10


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
        self._recent = _stored_recent(deps.scope)
        # The recent list changed — a tab was kept, retitled or found stale.
        self.recent_changed: Signal[()] = Signal()

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

    def recent(self) -> list[KeptTab]:
        """The tabs kept lately, newest first — as recorded; a reader asks
        ``tabs.live_address`` which of them still open."""
        return list(self._recent)

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
        self._remember_recent()
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

    def _remember_recent(self) -> None:
        """Put the current tab first if the person kept it, and write the list down.

        Titles are the tabs' own, refreshed for every tab still open, so a list read after
        the tab has closed says what the tab last said; the stamp is when the tab was last
        the one in front. An address that no longer opens is dropped here, so it cannot hold
        one of the few places.
        """
        tabs = self._deps.tabs
        recent = list(self._recent)
        current = tabs.current_activity()
        if current is not None and not tabs.is_preview(current):
            now = datetime.now(UTC).isoformat(timespec="seconds")
            recent = [KeptTab(current.uri, "", now)]
            recent += [entry for entry in self._recent if entry.uri != current.uri]
        titles = {activity.uri: tabs.tab_title(activity) for activity in tabs.activities()}
        recent = [
            entry._replace(title=titles.get(entry.uri) or entry.title)
            for entry in recent
            if tabs.live_address(entry.uri, self._deps.exists) is not None
        ][:RECENT_CAP]
        if recent == self._recent:
            return
        self._recent = recent
        set_scoped(self._deps.scope, MODULE_ID, RECENT_KEY, [entry._asdict() for entry in recent])
        self.recent_changed.emit()

    # -- reopening -----------------------------------------------------------------------------

    def _reopen(self) -> None:
        stored = get_scoped(self._deps.scope, MODULE_ID, OPEN_KEY, {})
        if not isinstance(stored, dict):
            return  # Written by something that is not this; there is nothing to restore.
        open_uris = stored.get("open")
        current = stored.get("current")
        self._restoring = True
        try:
            tabs, exists = self._deps.tabs, self._deps.exists
            for uri in open_uris if isinstance(open_uris, list) else []:
                tabs.reopen(uri, exists)
            # Opening it again is a plain focus, so the tab the user was on is current
            # without this module knowing anything about how focus works.
            tabs.reopen(current, exists)
        finally:
            self._restoring = False


def _stored_recent(scope: str) -> list[KeptTab]:
    """The recent list as last written; anything unreadable reads as nothing."""
    stored = get_scoped(scope, MODULE_ID, RECENT_KEY, [])
    recent: list[KeptTab] = []
    for entry in stored if isinstance(stored, list) else []:
        if isinstance(entry, dict) and isinstance(uri := entry.get("uri"), str):
            title, at = entry.get("title"), entry.get("at")
            recent.append(
                KeptTab(
                    uri, title if isinstance(title, str) else "", at if isinstance(at, str) else ""
                )
            )
    return recent
