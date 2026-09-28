"""Step statuses and the Control Centre: what needs a person right now — in one project, as a
tab beside its graph, or in every project at once.

The graph plans the work; these tabs are for the weeks the work is *happening*, and they ask
one question: what needs me? A table answers it, grouped the way the work comes back to a
person — Blocked, Waits for you, Ready to merge, Ready for review, Ready to start — with
Waiting, what cannot start yet, last. Work an agent is doing is not listed: it needs
nobody — unless the agent waits on a person, a plan to approve or a question to answer,
which is *Waits for you* (``asks_person``, the agent-run aspect's reading). The walk
itself is the domain's (``domain/progression.py``) — this module renders it and adds
nothing to the model, so the tabs, ``dplanner progression show`` and ``--json`` can never
disagree.

**Two tabs, one board.** :class:`StatusBoard` is everything the two share — the strip, the
table, the row's ⋮, the refresh — over the projects a subclass names. *Step statuses*
(:class:`ProgressionActivity`) is one project's; the **Control Centre**
(:class:`ControlCentreActivity`) is every project's, each row naming its own, with a
*Projects* filter on its strip. They are siblings rather than one class with a scope,
because a project's tab closes with its project (``follow_project_tabs``) and the Control
Centre has no project to close with. Each project is walked on its own and the board is
their merge (``progression.merge``), so a filter over projects re-merges what was walked
and never walks the graph again.

**The surface is named for the question, the derivation for the answer.** The tab is
*Step statuses*, with the count of rows needing a person in its title; the walk stays
``progression()`` and so does the verb, because the groups are only some of the partitions
it computes. The module id, the activity kind and the action ids are the on-disk and
in-registry contract and are untouched by the renaming.

Five seams, all established elsewhere in this application:

- **Statuses arrive as a function** (``status_for``), wired by the composition root from
  the status aspect's Qt-free reader — this module never learns what one is stored as. It
  reads today when asked, so both tabs re-run when the day turns (``clock.day_changed``):
  a step behind a dated wait joins Ready the morning it may start.
- **The ticked rows are the selection**, published as the selection scope, so the Step
  menu's verbs, the strip's and Run Agent's profiles all act on exactly them — across
  projects in the Control Centre, where every verb resolves each step's own project.
- **The strip seats registry verbs the root names** (``verbs``) — Run Agent with its
  profiles, the status verbs a person moves finished work on with — each restated on every
  context change, greyed with its own reason, and never a copy: this module never learns
  the agent or status modules exist.
- **A row's ⋮ renders the Step menu's bands about that step** (:data:`ROW_MENU`): its
  agent's terminal, a shell in its worktree, its pull request, its details, where it shows.
  It picks that row alone first, because the verbs about one step read the first picked.
- **Activating a row opens its details**, by running ``steps.details`` against a context
  naming exactly that row's step.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout, QWidget

from dplanner.core.clock import Clock
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.progression import Progression, merge, progression
from dplanner.domain.short_titles import UNTITLED
from dplanner.framework.action_menu import Band, build_menu, fill_bands
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    EntityActivity,
    follow_project,
    follow_project_tabs,
    project_tab_title,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry, SurfaceSegment
from dplanner.framework.segmented import Segmented
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState
from dplanner.modules.progression.view import ALL, GROUPS, StatusTable, needing_a_person
from dplanner.theme.icons import gauge_icon
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECTION_GAP

MODULE_ID = "progression"
PROGRESSION_KIND = "progression"
CONTROL_CENTRE_KIND = "control_centre"
CONTROL_CENTRE = "Control Centre"

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


def _pending(_step: Step) -> str:
    return "pending"


def _no_badge(_step_id: StepId) -> QIcon | None:
    return None


@dataclass(frozen=True)
class StripVerb:
    """A registry verb the strip seats over the ticked rows, the data child menu its arrow
    drops down, if it has one — Run Agent's profiles — and the words it wears beside its
    glyph, if any."""

    action_id: str
    data_menu: str | None = None
    face: str = ""


@dataclass(frozen=True)
class ProgressionDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    segments: IndexSegmentRegistry
    # The status claims, as answers — a wait read done once it is over. Wired by the
    # composition root from the status aspect's Qt-free reader; the honest default is a
    # build where nothing is claimed.
    status_for: Callable[[Step], str] = field(default=_pending)
    # Whose day it is: a wait is over on a day, so the boards re-run when it turns.
    clock: Clock = field(default_factory=Clock)
    # Whether a step is work at all: a wait is not, and is on no row and in no count.
    counts_as_work: Callable[[Step], bool] = field(default=lambda _step: True)
    # Whether a waiter may start once a source it requires is ready for review — an
    # auto-progress link, read through the owning aspect by the composition root.
    auto_progresses: Callable[[Step, Step], bool] = field(default=lambda _waiter, _source: False)
    # Whether a running step's agent waits on a person — a plan to approve, a question to
    # answer: the agent-run aspect's reading, which puts the row under *Waits for you*.
    asks_person: Callable[[Step], bool] = field(default=lambda _step: False)
    # The verbs a person runs over the ticked rows, named by the composition root: which
    # they are is a fact about other modules. None seated is a build without them.
    verbs: tuple[StripVerb, ...] = ()
    # A milestone's key and its own shade of the project's colour map, or None for a step
    # that is not one — the badge its row leads with. Wired by the composition root: which
    # map a project uses is one module's assumption and the key is another's letter.
    milestone_badge: Callable[[StepId], QIcon | None] = field(default=_no_badge)
    # The step's key, under its title, and the canvas medallion naming what it is.
    key_of: Callable[[Step], str] = field(default=lambda _step: "")
    glyph_of: Callable[[Step], str] = field(default=lambda _step: "step")


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

    def __init__(self, deps: ProgressionDeps, entity_kind: str, entity_id: NodeId) -> None:
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

        library = deps.library
        self.table = StatusTable(
            key_of=deps.key_of,
            glyph_of=deps.glyph_of,
            milestone_badge=deps.milestone_badge,
            project_of=lambda step: library.project_of(step.id).title or UNTITLED,
            parent=page,
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_row_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.menu_requested.connect(self._drop_row_menu)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

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
                deps.library,
                project,
                deps.status_for,
                deps.counts_as_work,
                deps.auto_progresses,
                deps.asks_person,
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

    def __init__(self, deps: ProgressionDeps, project_id: NodeId) -> None:
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
    """

    def __init__(self, deps: ProgressionDeps) -> None:
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
        self._refresh()

    @property
    def uri(self) -> Uri:
        return activity_uri(CONTROL_CENTRE_KIND)

    @property
    def title(self) -> str:
        return f"{CONTROL_CENTRE} ({self._needing})" if self._needing else CONTROL_CENTRE

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


class ProgressionModule:
    id = MODULE_ID

    def __init__(self, deps: ProgressionDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(PROGRESSION_KIND, project_id, preview=preview)

    def open_control_centre(self, *, preview: bool = False) -> None:
        self._deps.tabs.open(CONTROL_CENTRE_KIND, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProgressionActivity:
            assert target is not None
            return ProgressionActivity(deps, target)

        deps.tabs.register_factory(PROGRESSION_KIND, factory)
        # One tab for the library: whatever target it is asked for, its address is the one.
        deps.tabs.register_factory(CONTROL_CENTRE_KIND, lambda _target: ControlCentreActivity(deps))
        deps.actions.register(
            ActionSpec(
                id="progression.open",
                label="Step Stat&uses",
                menu="Go",
                group="views",
                order=30,
                tip="What needs a person right now: blocked, to merge, to review, to start",
                state=self._on_a_project,
                run=self._open,
            )
        )
        # The same verb's second seat, in Step ▸ Show in beside Order's, so a table's
        # right-click reaches it. palette=False: one palette entry.
        deps.actions.register(
            ActionSpec(
                id="progression.open_step",
                label="Step Stat&uses",
                menu="Step",
                group="surfaces",
                submenu="Show in",
                order=30,
                tip="What needs a person right now: blocked, to merge, to review, to start",
                palette=False,
                state=self._on_a_project,
                run=self._open,
            )
        )
        # Beside Home, in the index and in Go: a place of the library's rather than one
        # project's.
        deps.segments.register(
            IndexSegment(
                id=CONTROL_CENTRE_KIND,
                label=CONTROL_CENTRE,
                factory=lambda _root: SurfaceSegment(
                    lambda preview: self.open_control_centre(preview=preview)
                ),
                order=5,  # Between Home (0) and Projects (10).
                icon=gauge_icon,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="progression.control_centre",
                label="Co&ntrol Centre",
                menu="Go",
                group="home",
                order=20,
                tip="What needs a person in every project: blocked, to merge, to review, to start",
                icon=gauge_icon,
                run=lambda _context: self.open_control_centre(),
            )
        )
        follow_project_tabs(deps.tabs, ProgressionActivity, deps.library)

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if focused_project(context, self._deps.library) is None else ENABLED

    def _open(self, context: Context) -> None:
        project = focused_project(context, self._deps.library)
        if project is not None:
            self.open(project.id)
