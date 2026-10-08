"""The Step statuses tab and the Control Centre: what needs a person right now, grouped, a
box on every row — one project's, or every project's in the Control Centre.

Pure rendering — the planning tier's :class:`~dplanner.planning.progression.Progression` arrives
computed and the table is rebuilt wholesale, so nothing here can disagree with the model.
The groups are the partitions a person acts on — Blocked and Waits for you, what is stuck
on a person, then in the order the work is closest to done Ready to merge, Ready for
review, Ready to start — and then Waiting, what cannot start yet. Work in progress is not
listed: an agent at work needs nobody, and the tab is for the rows that do — which is why
an agent that waits on a person (a plan to approve, a question) is, and why work under
review that an agent takes on (a review of it, a collector) is not.

**The box is the selection.** The first column is a check column (``Column(check=True)``):
ticking a row picks it, and the host publishes what is picked, so the strip's verbs, the
right-click Step menu and Run Agent's profiles all act on exactly the ticked rows. The
picks survive a rebuild by step id — an accepted review is still ticked in its new group.

A row's glyph is Find's: a milestone's key as a badge in its own shade, otherwise who works
the step — the glyph its key block wears — painted in the palette's ink, so a palette change
paints the rows again (``changeEvent``): a colour taken out of the palette goes stale.

**A row names its project only where the rows span several** — the Project column stands
down on one project's tab, where every row would say the same. **And a row ends in its ⋮**
(``Column(menu=True)``): the host builds that row's verbs when it is pressed.

**Two tabs, one board.** :class:`StatusBoard` is everything the two share — the strip, the
table, the row's ⋮, the refresh — over the projects a subclass names. *Step statuses*
(:class:`ProgressionActivity`) is one project's; the **Control Centre**
(:class:`ControlCentreActivity`) is every project's, each row naming its own, with a
*Projects* filter on its strip. They are siblings rather than one class with a scope,
because a project's tab closes with its project (``follow_project_tabs``) and the Control
Centre has no project to close with. Each project is walked on its own and the board is
their merge (``progression.merge``), so a filter over projects re-merges what was walked
and never walks the graph again.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSplitter, QVBoxLayout, QWidget

from dplanner.domain.model import NodeId, Project, Step, StepId
from dplanner.domain.short_titles import UNTITLED
from dplanner.framework.action_menu import Band, build_menu, fill_bands
from dplanner.framework.activity import (
    EntityActivity,
    follow_project,
    project_tab_title,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.segmented import Segmented
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState
from dplanner.planning.progression import Progression, merge, progression
from dplanner.theme.icons import glyph_painter, step_icon
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECONDARY_ALPHA, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.status_board.module import ProgressionDeps, QuestionLane

PROGRESSION_KIND = "progression"
CONTROL_CENTRE_KIND = "control_centre"
CONTROL_CENTRE = "Control Centre"


STEP_ROLE = HOST_ROLE
CHECK_COLUMN, STEP_COLUMN, PROJECT_COLUMN, UNBLOCKS_COLUMN, MENU_COLUMN = range(5)
COLUMNS = (
    Column("", check=True),
    Column("Step", glyph=True, detail=True, resize="stretch"),
    Column("Project"),
    Column("Unblocks", numeric=True),
    Column("", menu=True),
)
ROW_MENU_TIP = "What you can do with this step"

ALL = "all"


@dataclass(frozen=True)
class Group:
    """One kind of row: its key (the filter's value and the heading's fold), the heading's
    words, the filter's word, what the table says when it is the only one and empty, its
    steps in the order the derivation ranked them, and whether they wait on a person —
    everything but Waiting does, which is the rest of the plan."""

    key: str
    heading: str
    label: str
    empty: str
    rows: Callable[[Progression], tuple[Step, ...]]
    needs_person: bool = True


GROUPS = (
    Group("blocked", "Blocked", "Blocked", "Nothing is blocked.", lambda found: found.attention),
    Group(
        "asking",
        "Waits for you",
        "Answer",
        "No agent is waiting for you.",
        lambda found: found.asking,
    ),
    Group(
        "merge",
        "Ready to merge",
        "Merge",
        "Nothing is waiting on a merge.",
        lambda found: found.merge,
    ),
    Group(
        "review",
        "Ready for review",
        "Review",
        "Nothing is ready for review.",
        lambda found: found.review,
    ),
    Group(
        "start", "Ready to start", "Start", "Nothing is ready to start.", lambda found: found.ready
    ),
    Group(
        "waiting",
        "Waiting",
        "Waiting",
        "Nothing is waiting.",
        lambda found: (*(coming.step for coming in found.upcoming), *found.waiting),
        needs_person=False,
    ),
)


def needing_a_person(progress: Progression) -> int:
    return sum(len(group.rows(progress)) for group in GROUPS if group.needs_person)


class StatusTable(Table):
    """The rows, grouped; ``show_rows`` rebuilds them for one filter."""

    def __init__(
        self,
        *,
        key_of: Callable[[Step], str],
        glyph_of: Callable[[Step], str],
        milestone_badge: Callable[[StepId], QIcon | None],
        project_of: Callable[[Step], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(COLUMNS, selection="extended", parent=parent)
        self._key_of = key_of
        self._glyph_of = glyph_of
        self._milestone_badge = milestone_badge
        self._project_of = project_of
        self._shown: tuple[Progression, str, bool] | None = None
        # Each glyph painted once per fill, in that fill's ink: a board is hundreds of rows
        # wearing three pictures, and an SVG rendered per row was a third of the fill.
        self._glyphs: dict[str, QIcon] = {}

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """The glyphs again, in the new theme's ink.

        ``getattr``, not a plain read: Qt delivers a PaletteChange from inside
        ``QTableWidget.__init__``, before this class's own state exists.
        """
        shown = getattr(self, "_shown", None)
        if event.type() == QEvent.Type.PaletteChange and shown is not None:
            progress, group, spans = shown
            self.show_rows(progress, group, spans=spans)
        super().changeEvent(event)

    def show_rows(self, progress: Progression, shown: str, *, spans: bool = False) -> None:
        """Every group ``shown`` names — one, or all of them — keeping the picks; ``spans``
        when the rows come from several projects, which is when each names its own.

        Quiet while the rows are replaced: clearing and reselecting would announce the
        selection twice, so the host hears one change or none (``picked`` tells it which).
        """
        self._shown = (progress, shown, spans)
        self.setColumnHidden(PROJECT_COLUMN, not spans)
        picked = self.picked()
        self._glyphs.clear()
        self.blockSignals(True)
        try:
            self.clear_rows()
            for group in GROUPS:
                steps = group.rows(progress)
                if shown not in (ALL, group.key) or not steps:
                    continue
                if shown == ALL:  # One group on its own needs no heading: the filter says it.
                    self.add_heading(group.heading, key=group.key)
                for step in steps:
                    self._add(step, progress.unlocks.get(step.id, 0))
            self._reselect(picked)
        finally:
            self.blockSignals(False)

    def _add(self, step: Step, unlocks: int) -> None:
        self.add_row(
            (
                Cell(),
                Cell(
                    step.title or "Untitled step",
                    detail=self._key_of(step),
                    glyph=self._glyph(step),
                ),
                Cell(self._project_of(step)),
                Cell(str(unlocks) if unlocks else ""),
                Cell(tooltip=ROW_MENU_TIP),
            ),
            data={STEP_ROLE: step.id},
        )

    def _glyph(self, step: Step) -> QIcon:
        badge = self._milestone_badge(step.id)
        if badge is not None:
            return badge
        name = self._glyph_of(step)
        if name not in self._glyphs:
            ink = QColor(self.palette().text().color())
            ink.setAlpha(SECONDARY_ALPHA)
            self._glyphs[name] = (glyph_painter(name) or step_icon)(ink)
        return self._glyphs[name]

    # -- reading it back ------------------------------------------------------------------

    def step_at(self, row: int) -> StepId | None:
        item = self.item(row, STEP_COLUMN)
        found = item.data(STEP_ROLE) if item is not None else None
        return found if isinstance(found, str) else None

    def steps(self) -> list[StepId]:
        """Every step listed, top to bottom."""
        return [step_id for row in range(self.rowCount()) if (step_id := self.step_at(row))]

    def picked(self) -> list[StepId]:
        """The ticked steps, top to bottom."""
        rows = sorted({index.row() for index in self.selectedIndexes()})
        return [step_id for row in rows if (step_id := self.step_at(row)) is not None]

    def row_of(self, step_id: StepId) -> int | None:
        return next((row for row in range(self.rowCount()) if self.step_at(row) == step_id), None)

    def _reselect(self, step_ids: list[StepId]) -> None:
        """Keep the picks across a rebuild, by step — the rows are new."""
        wanted = set(step_ids)
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        model = self.selectionModel()
        for row in range(self.rowCount()):
            if self.step_at(row) in wanted:
                model.select(self.model().index(row, STEP_COLUMN), flags)


FILTERS = (
    (ALL, "All", "Everything that needs a person, then what is waiting"),
    *((group.key, group.label, group.heading) for group in GROUPS),
)
NO_STEPS = "No steps yet."
NOTHING_NEEDED = "Nothing needs you right now."

# What a row's ⋮ drops: the Step menu's bands about the step itself that a person reaches for
# from a board — its agent and what follows one, then where it is seen. Rendered, never
# copied, so a verb registered into either band appears here with nothing written.
ROW_MENU: Final = (Band("Step", ("agent", "open", "surfaces")),)


def _nodes(step_ids: list[StepId]) -> tuple[ContextNode, ...]:
    return tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)


class StatusBoard(EntityActivity):
    """What needs a person over some projects: the strip, the table, the row's ⋮ and the
    refresh both tabs share.

    A subclass names its projects (:meth:`_projects`), whether its rows span several
    (:meth:`_spans`) and which of them are shown (:meth:`_shown_projects`), subscribes to
    what it follows into ``_unsubscribes``, and ends its ``__init__`` with ``_refresh()`` —
    after its own strip controls exist, since the first refresh reads them.
    """

    def __init__(self, deps: "ProgressionDeps", entity_kind: str, entity_id: NodeId) -> None:
        super().__init__(deps.context, entity_kind, entity_id)
        self._deps = deps
        self._filter = ALL
        self._each: dict[NodeId, Progression] = {}  # Each project's walk, in library order.
        self._found: Progression | None = None  # What the table shows: the shown walks merged.
        self._needing = 0

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        # The strip: what acts on the ticked rows, then which rows to look at.
        strip = QHBoxLayout()
        layout.addLayout(strip)  # Before it is filled: a parentless layout leaks its items.
        strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(page)
        for verb in deps.verbs:
            self.controls.add_action(
                deps.actions,
                deps.context,
                verb.action_id,
                data_menu=verb.data_menu,
                face=verb.face,
            )
        if deps.verbs:
            self.controls.add_divider()
        self.filter = Segmented(FILTERS, page)
        self.filter.set_value(ALL)
        self.filter.picked.connect(lambda value: self.set_filter(str(value)))
        self.controls.add_widget(self.filter)
        strip.addWidget(self.controls, 1)
        # Outside the strip, so folding the verbs into … can never take it.
        self.updating = UpdatingIndicator(page)
        strip.addWidget(self.updating)

        # The board under a seam, so whatever a tab puts above it — the Control Centre's
        # question cards — takes the share a person drags it to.
        self.split = QSplitter(Qt.Orientation.Vertical, page)
        self.split.setChildrenCollapsible(False)
        layout.addWidget(self.split, 1)
        board = QWidget()
        self.split.addWidget(board)
        rows = QVBoxLayout(board)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)

        library = deps.library
        self.table = StatusTable(
            key_of=deps.key_of,
            glyph_of=deps.glyph_of,
            milestone_badge=deps.milestone_badge,
            project_of=lambda step: library.project_of(step.id).title or UNTITLED,
            parent=board,
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_row_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.menu_requested.connect(self._drop_row_menu)
        rows.addWidget(self.table, 1)
        self.empty = EmptyState(parent=board, stands_in_for=self.table)
        rows.addWidget(self.empty, 1)

        self._widget = page
        # After a quiet spell, not per signal: every row is rebuilt.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            deps.clock.day_changed.connect(lambda _day: self._refresh_soon.trigger()),
        ]

    # -- what a subclass says ------------------------------------------------------------------

    def _projects(self) -> Sequence[Project]:
        raise NotImplementedError

    def _spans(self) -> bool:
        """Whether the rows come from several projects, and so each names its own."""
        return False

    def _shown_projects(self) -> list[NodeId]:
        return list(self._each)

    # -- the activity contract -----------------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._on_selection()

    def close(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.controls.dispose()

    # -- which rows ----------------------------------------------------------------------------

    def set_filter(self, key: str) -> None:
        """Look at one group — a ``GROUPS`` key — or at all of them (``ALL``)."""
        self._filter = key
        self.filter.set_value(key)
        self._show()

    @property
    def filter_key(self) -> str:
        return self._filter

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        deps = self._deps
        self._each = {
            project.id: progression(
                deps.library, project, deps.status_for, deps.counts_as_work, deps.asks_person
            )
            for project in self._projects()
        }
        self._show()
        # Every row needing a person on the board, whatever the filters are showing.
        needing = needing_a_person(merge(self._each.values()))
        if needing != self._needing:
            self._needing = needing
            deps.tabs.set_tab_title(self, self.title)

    def _show(self) -> None:
        found = self._found = merge(self._each[project_id] for project_id in self._shown_projects())
        before = self.table.picked()
        self.table.show_rows(found, self._filter, spans=self._spans())
        if self.table.picked() != before:
            self._on_selection()  # A ticked step left the rows shown.
        if self.table.rowCount():
            self.empty.say("")
        elif not found.total:
            self.empty.say(NO_STEPS)
        elif self._filter == ALL:
            self.empty.say(NOTHING_NEEDED)
        else:
            self.empty.say(next(group.empty for group in GROUPS if group.key == self._filter))

    # -- speaking for the user -----------------------------------------------------------------

    def _on_selection(self) -> None:
        self.publish_selection(_nodes(self.table.picked()))

    def _on_row_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            # Against a context naming exactly this row's step, not the service's — the
            # double-click means the row under it even if a publish was suppressed.
            context = Context({SCOPE_SELECTION: _nodes([step_id])})
            self._deps.actions.run("steps.details", context)

    def _on_context_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        step_id = self.table.step_at(row)
        if step_id is None:
            return
        if step_id not in self.table.picked():
            self.table.selectRow(row)
        menu: QMenu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def row_menu(self, row: int) -> QMenu | None:
        """What one row's ⋮ offers, built for this opening — that row picked alone first.

        Alone, where a right-click keeps a pick the row is in: the verbs about one step —
        its terminal, its pull request, a shell in its worktree — act on the first picked,
        and a ⋮ pressed on the third of three ticked rows is about the third.
        """
        if self.table.step_at(row) is None:
            return None
        self.table.pick_row(row)
        deps = self._deps
        return fill_bands(QMenu(self.table), ROW_MENU, deps.actions, deps.context)

    def _drop_row_menu(self, row: int, at: QPoint) -> None:
        menu = self.row_menu(row)
        if menu is not None:
            menu.exec(at)
            menu.deleteLater()


class ProgressionActivity(StatusBoard):
    """One project's Step statuses."""

    def __init__(self, deps: "ProgressionDeps", project_id: NodeId) -> None:
        super().__init__(deps, "project", project_id)
        self.project_id = project_id
        library = deps.library
        # This project only, and no prose: the table reads statuses, titles and links.
        self._unsubscribes.append(
            follow_project(
                library,
                project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.structure_changed,
                    library.edges_changed,
                    library.field_changed,
                    library.module_data_changed,
                ),
            )
        )
        self._refresh()

    @property
    def uri(self) -> Uri:
        return activity_uri(PROGRESSION_KIND, self.project_id)

    @property
    def title(self) -> str:
        """The project, and how many rows need a person — said only when some do."""
        count = f" ({self._needing})" if self._needing else ""
        return project_tab_title(self._deps.library, self.project_id, f"Step statuses{count}")

    def _projects(self) -> Sequence[Project]:
        library = self._deps.library
        # A deleted project's tab is about to close; until then it has nothing to walk.
        return (library.project(self.project_id),) if library.has(self.project_id) else ()


class ControlCentreActivity(StatusBoard):
    """Every project's Step statuses as one board — what needs a person anywhere.

    Its rows name their projects and its strip adds a **Projects** filter, offered while
    the library has more than one: a project is added to it as it arrives, renamed with it,
    and hidden — and dropped from the pick — when it leaves, since a filter that stops
    listing what it is narrowing by hides rows for a reason nobody can see.

    **The open questions sit on top**, a card each, above the board (``question_cards``):
    narrowed by the same filter, and counted with the rows in the title. A headless run
    parked on a question sets no agent state, so a card and a *Waits for you* row are
    hardly ever the same step, and the plain sum is the honest count.
    """

    def __init__(self, deps: "ProgressionDeps") -> None:
        library = deps.library
        super().__init__(deps, "library", library.id)
        self.projects = FilterButton(self.widget, label="Projects")
        self.controls.add_widget(self.projects)
        self._offered: dict[NodeId, QAction] = {}
        # Every project's changes: the board is all of them.
        self._unsubscribes += [
            signal.connect(lambda *_args: self._refresh_soon.trigger())
            for signal in (
                library.structure_changed,
                library.edges_changed,
                library.field_changed,
                library.module_data_changed,
            )
        ]
        self._unsubscribes.append(self.projects.changed.connect(self._show))
        self.questions: QuestionLane | None = None
        if deps.question_cards is not None:
            self.questions = deps.question_cards(self.split)
            self.split.insertWidget(0, self.questions.widget)
            self.split.setStretchFactor(0, 0)
            self.split.setStretchFactor(1, 1)
            self.questions.set_changed(self._cards_changed)
        self._refresh()

    @property
    def uri(self) -> Uri:
        return activity_uri(CONTROL_CENTRE_KIND)

    @property
    def title(self) -> str:
        count = self._needing + (self.questions.count if self.questions is not None else 0)
        return f"{CONTROL_CENTRE} ({count})" if count else CONTROL_CENTRE

    def _cards_changed(self) -> None:
        """A card came or went: the title counts it, and the seam goes back to the cards'
        own height — a lane kept at the size of four cards when one is left is a hole."""
        self._deps.tabs.set_tab_title(self, self.title)
        if self.questions is None:
            return
        total = sum(self.split.sizes())
        wanted = self.questions.widget.sizeHint().height()
        if total > wanted:
            self.split.setSizes([wanted, total - wanted])

    def close(self) -> None:
        if self.questions is not None:
            self.questions.close()
        super().close()

    def activity_nodes(self) -> tuple[ContextNode, ...]:
        """No project: the board is every project's, and a verb about one reads the picked
        step's own (``focused_project``)."""
        return (ContextNode(self.uri),)

    def _projects(self) -> Sequence[Project]:
        return tuple(self._deps.library.projects)

    def _spans(self) -> bool:
        return len(self._each) > 1

    def _shown_projects(self) -> list[NodeId]:
        picked = set(self.projects.active())
        return [project_id for project_id in self._each if not picked or project_id in picked]

    def _refresh(self) -> None:
        # The walk first: withdrawing a project from the pick announces the filter, and the
        # board it re-shows must already be the one without that project.
        super()._refresh()
        self._sync_projects()
        if self.questions is not None:
            self.questions.refresh()  # A step renamed or a project gone says so on its card.

    def _show(self) -> None:
        super()._show()
        if self.questions is not None:
            self.questions.show_projects(self.projects.active())

    def _sync_projects(self) -> None:
        """The filter's entries against the library: one per project, in the words it has
        now, the ones that left hidden and no longer picked."""
        projects = self._deps.library.projects
        here = {project.id for project in projects}
        for project in projects:
            words = project.title or UNTITLED
            offered = self._offered.get(project.id)
            if offered is None:
                self._offered[project.id] = self.projects.add_filter(project.id, words)
            elif offered.text() != words:
                self.projects.relabel(project.id, words)
        for project_id, offered in self._offered.items():
            offered.setVisible(project_id in here)
        picked = set(self.projects.active())
        if picked - here:
            self.projects.set_active(picked & here)
        self.controls.set_shown(self.projects, len(projects) > 1)
