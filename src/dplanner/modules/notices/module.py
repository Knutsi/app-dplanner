"""The notices module: the sources' switches, the scan, the bell and the tab.

The module keeps three things and derives the rest. **Which sources are on** and **which
notices are muted** are per-user preferences (``user_config``); **what stands** is asked
of every switched-on source on a slow timer, on demand, and whenever a source says it
changed — never stored. A mute names one notice (``source:key``) and is dropped the moment
that notice is absent from a scan, so a condition that clears and returns is heard again.

Open on a notice goes to one of three places the window already knows how to reach: a
step through the composition root's ``reveal``, a tab through ``tabs.open``, a verb
through the action registry. The module learns nothing about what any of them is.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer

from dplanner.core.signals import Signal
from dplanner.domain.notice import Notice
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.window import MenuCornerHost
from dplanner.modules.notices.activity import NOTICES_KIND, NoticesActivity
from dplanner.modules.notices.sources import NoticeSource, mute_key
from dplanner.modules.notices.view import NoticeBell
from dplanner.theme.icons import bell_icon
from dplanner.theme.themes import Theme

MODULE_ID = "notices"
SOURCES_KEY = "sources"  # {source id: bool} — absent is off: every source is opt-in.
MUTED_KEY = "muted"  # ["source:key", …]
# A standing condition changes slowly; the sources with a poller of their own say
# ``changed`` sooner. The timer runs only while a source is on.
SCAN_MS = 60_000


@dataclass(frozen=True)
class Standing:
    """One row of the inbox: the notice, whose it is, and whether it is muted."""

    source: NoticeSource
    notice: Notice
    muted: bool


@dataclass(frozen=True)
class NoticesDeps:
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    theme: ThemeService
    corner: MenuCornerHost
    debounce: DebounceService
    parent: QObject  # Owns the timer and the coalescer.
    # Select a step in its project — the composition root's ``reveal_step``.
    reveal: Callable[[str], None]
    # Every module's answer to "what stands", assembled by the root in the tab's order.
    sources: tuple[NoticeSource, ...]


class NoticesModule:
    id = MODULE_ID

    def __init__(self, deps: NoticesDeps) -> None:
        self._deps = deps
        self._on: dict[str, bool] = {}
        self._muted: set[str] = set()
        self._standing: list[Standing] = []
        self.changed: Signal[()] = Signal("notices.changed")

    def register(self) -> None:
        deps = self._deps
        remembered = get_global(MODULE_ID, SOURCES_KEY, {})
        self._on = {
            source.id: bool(isinstance(remembered, dict) and remembered.get(source.id, False))
            for source in deps.sources
        }
        self._muted = set(get_global(MODULE_ID, MUTED_KEY, []))

        self.bell = NoticeBell()
        self.bell.clicked.connect(lambda: self.open_tab())
        deps.corner.set_menu_corner_widget(self.bell)

        def paint(theme: Theme) -> None:
            self.bell.set_icon(bell_icon(theme.text_secondary))

        deps.theme.changed.connect(paint)
        paint(deps.theme.current)

        self._rescan = Debounced(self.rescan, parent=deps.parent, service=deps.debounce)
        for source in deps.sources:
            source.changed.connect(self._rescan.trigger)
        self._timer = QTimer(deps.parent)
        self._timer.setInterval(SCAN_MS)
        self._timer.timeout.connect(self.rescan)

        def factory(_target: str | None) -> NoticesActivity:
            return NoticesActivity(self, deps.context, deps.theme)

        deps.tabs.register_factory(NOTICES_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="notices.show",
                label="&Notices…",
                menu="View",
                group="panels",
                order=50,
                tip="What stands and needs a look when there is time: the inbox and its sources",
                run=lambda _context: self.open_tab(),
            )
        )

        for source in deps.sources:
            if self._on[source.id]:
                source.start()
        self._settle_timer()
        self.rescan()

    # -- the switches ----------------------------------------------------------------------

    def sources(self) -> tuple[NoticeSource, ...]:
        return self._deps.sources

    def is_on(self, source_id: str) -> bool:
        return self._on.get(source_id, False)

    def any_on(self) -> bool:
        return any(self._on.values())

    def set_on(self, source_id: str, on: bool) -> None:
        if self._on.get(source_id) == on:
            return
        self._on[source_id] = on
        set_global(MODULE_ID, SOURCES_KEY, dict(self._on))
        source = next(source for source in self._deps.sources if source.id == source_id)
        if on:
            source.start()
        else:
            source.stop()
        self._settle_timer()
        self.rescan()

    def _settle_timer(self) -> None:
        if self.any_on():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    # -- what stands -----------------------------------------------------------------------

    def rescan(self) -> None:
        found: list[tuple[NoticeSource, Notice]] = []
        for source in self._deps.sources:
            if self._on[source.id]:
                found.extend((source, notice) for notice in source.scan())
        present = {mute_key(source.id, notice) for source, notice in found}
        # A mute is "until it changes": one whose notice has cleared is forgotten, so the
        # condition is heard again if it comes back.
        if self._muted - present:
            self._muted &= present
            set_global(MODULE_ID, MUTED_KEY, sorted(self._muted))
        self._standing = [
            Standing(source, notice, mute_key(source.id, notice) in self._muted)
            for source, notice in found
        ]
        self.bell.show_notices([row.notice.title for row in self._standing if not row.muted])
        self.changed.emit()

    def standing(self) -> list[Standing]:
        """Every notice that stands, the live ones first and the muted after them."""
        return sorted(self._standing, key=lambda row: row.muted)

    def set_muted(self, row: Standing, muted: bool) -> None:
        key = mute_key(row.source.id, row.notice)
        if muted:
            self._muted.add(key)
        else:
            self._muted.discard(key)
        set_global(MODULE_ID, MUTED_KEY, sorted(self._muted))
        self.rescan()

    # -- going there -----------------------------------------------------------------------

    def go_to(self, notice: Notice) -> None:
        kind, *rest = notice.target
        deps = self._deps
        if kind == "step" and rest:
            deps.reveal(rest[0])
        elif kind == "tab" and rest:
            target = rest[1] if len(rest) > 1 else ""
            deps.tabs.open(rest[0], target or None)
        elif kind == "action" and rest:
            deps.actions.run(rest[0], deps.context.current())

    def open_tab(self) -> None:
        self._deps.tabs.open(NOTICES_KIND)
