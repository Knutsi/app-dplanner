"""Home's page: the getting-started guide beside the tabs this library kept lately.

The Home tab's widget. It follows what it shows for as long as it lives and lets go when Qt
destroys it, which is when the tab host drops a closed tab's page.

**The guide's buttons are the verbs themselves.** Each is restated from its ``ActionSpec`` on
every context change and runs through the registry, as a menu entry does — so a verb that
needs a project greys in its own words until one is picked in the index.

**A recent row reopens with one click**, through ``tabs.reopen``: the checks the session's
own reopen asks, so a row whose project has gone is simply not listed. The click swaps this
page away under the pointer, and Qt hands a habitual second click to whatever replaced it as
a double-click — on the graph, a new step — so that one double-click is dropped
(:class:`_SecondClickGuard`).
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QGuiApplication, QShowEvent, QWindow
from PySide6.QtWidgets import QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget

from dplanner.domain.model import NodeId
from dplanner.domain.plan_repo import ago
from dplanner.framework.action_registry import ActionState
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, activity_uri
from dplanner.framework.list_rows import DETAIL_ROLE, HOST_ROLE, RichList
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.toolbar import action_words
from dplanner.framework.widgets import EmptyState, caption
from dplanner.modules.home.guide import GUIDE, GuideStep
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.home.module import HomeDeps

HOME_KIND = "home"
GUIDE_CAPTION = "Getting started"
RECENT_CAPTION = "Recent"
NOTHING_RECENT = "Nothing opened yet. A view you keep open is listed here."
ADDRESS_ROLE = HOST_ROLE  # A recent row's tab address.


class GuideRow(WellRow):
    """One step of the guide: its title, its words under it, and its verb at the right."""

    def __init__(self, step: GuideStep, page: "HomePage") -> None:
        super().__init__(step.title)
        self.set_note(step.words)
        self.button = self.add_button("", lambda: page.run(step))


class HomePage(QWidget):
    def __init__(self, deps: "HomeDeps", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._deps = deps
        layout = QHBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        guide = QVBoxLayout()
        layout.addLayout(guide, 1)  # Before it is filled: a parentless layout leaks its items.
        guide.setSpacing(CAPTION_GAP)
        guide.addWidget(caption(GUIDE_CAPTION, self))
        self.guide = RowWell(self)
        guide.addWidget(self.guide, 1)

        recent = QVBoxLayout()
        layout.addLayout(recent, 1)
        recent.setSpacing(CAPTION_GAP)
        recent.addWidget(caption(RECENT_CAPTION, self))
        self.recent = RichList(self)
        self.recent.itemClicked.connect(self.reopen)
        self.recent.itemActivated.connect(self.reopen)
        recent.addWidget(self.recent, 1)
        self.empty = EmptyState(parent=self, stands_in_for=self.recent)
        recent.addWidget(self.empty, 1)

        unsubscribe = [
            deps.context.changed.connect(lambda _context: self.restate()),
            deps.watch_recent(self.list_recent),
            deps.library.structure_changed.connect(self._on_structure),
        ]
        self.destroyed.connect(lambda: [each() for each in unsubscribe])
        self.restate()
        self.list_recent()

    # -- the guide -----------------------------------------------------------------------------

    def restate(self) -> None:
        """Say what each verb says right now: its words, whether it runs, and why not. A
        verb this build does not have (hidden, not greyed) takes its step with it."""
        context = self._deps.context.current()
        states = {step: self._deps.actions.spec(step.action).state(context) for step in GUIDE}
        self.guide.reconcile(
            [step for step in GUIDE if states[step].visible],
            lambda step: GuideRow(step, self),
            lambda step, row: self._restate(step, row, states[step]),
        )

    def _restate(self, step: GuideStep, row: GuideRow, state: ActionState) -> None:
        words, tip = action_words(self._deps.actions.spec(step.action), state)
        row.button.setText(words)
        row.button.setToolTip(tip)
        row.button.setEnabled(state.enabled)

    def run(self, step: GuideStep) -> None:
        self._deps.actions.run(step.action, self._deps.context.current())

    # -- the recent tabs -----------------------------------------------------------------------

    def list_recent(self) -> None:
        deps = self._deps
        home = activity_uri(HOME_KIND)
        self.recent.clear()
        for kept in deps.recent():
            if kept.uri == home or deps.tabs.live_address(kept.uri, deps.library.has) is None:
                continue
            item = QListWidgetItem(kept.title or kept.uri)
            item.setData(DETAIL_ROLE, ago(kept.at))
            item.setData(ADDRESS_ROLE, kept.uri)
            self.recent.addItem(item)
        self.empty.say("" if self.recent.count() else NOTHING_RECENT)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        """Say again how long ago each tab was kept: the words age while nobody looks."""
        self.list_recent()
        super().showEvent(event)

    def reopen(self, item: QListWidgetItem) -> None:
        opened = self._deps.tabs.reopen(item.data(ADDRESS_ROLE), self._deps.library.has)
        window = self.window().windowHandle()
        if opened is not None and window is not None:
            _SecondClickGuard(window)

    def _on_structure(self, parent_id: NodeId, *_rest: object) -> None:
        if parent_id == self._deps.library.id:
            self.list_recent()  # A project joined or left: its rows come or go with it.


class _SecondClickGuard(QObject):
    """Drops the double-click a habitual second click would make on whatever replaced the
    row that was clicked, for one double-click interval.

    Qt decides a press is a double-click by time and distance alone, and delivers it to the
    widget under the pointer — after a row that swaps its page away, the tab that has just
    opened. The filter sits on the ``QWindow``, which sees an event before any widget does,
    so only this window is watched, and only for as long as a double-click can take.
    """

    def __init__(self, window: QWindow) -> None:
        super().__init__(window)
        self._window = window
        window.installEventFilter(self)
        interval = QGuiApplication.styleHints().mouseDoubleClickInterval()
        QTimer.singleShot(interval, self, self._stop)  # The guard as context: gone, not run.

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._stop()
            return True
        return super().eventFilter(watched, event)

    def _stop(self) -> None:
        self._window.removeEventFilter(self)
        self.deleteLater()


class HomeActivity(ActivityBase):
    """The Home tab: the page once more, as a tab kept open beside the others."""

    def __init__(self, deps: "HomeDeps") -> None:
        self._context = deps.context
        self.uri = activity_uri(HOME_KIND)
        self.title = "Home"
        self.widget = HomePage(deps)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
