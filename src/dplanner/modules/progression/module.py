"""Step statuses: what needs a person in a project right now — as a tab beside its graph.

The graph plans the work; this tab is for the weeks the work is *happening*, and it asks one
question: what needs me? A table answers it, grouped the way the work comes back to a
person — Blocked, Ready to merge, Ready for review, Ready to start — with Waiting, what
cannot start yet, last. Work an agent is doing is not listed: it needs nobody. The walk
itself is the domain's (``domain/progression.py``) — this module renders it and adds
nothing to the model, so the tab, ``dplanner progression show`` and ``--json`` can never
disagree.

**The surface is named for the question, the derivation for the answer.** The tab is
*Step statuses*, with the count of rows needing a person in its title; the walk stays
``progression()`` and so does the verb, because the groups are only some of the partitions
it computes. The module id, the activity kind and the action ids are the on-disk and
in-registry contract and are untouched by the renaming.

Four seams, all established elsewhere in this application:

- **Statuses arrive as a function** (``status_for``), wired by the composition root from
  the status aspect's Qt-free reader — this module never learns what one is stored as.
- **The ticked rows are the selection**, published as the selection scope, so the Step
  menu's verbs, the strip's and Run Agent's profiles all act on exactly them.
- **The strip seats registry verbs the root names** (``verbs``) — Run Agent with its
  profiles, the status verbs a person moves finished work on with — each restated on every
  context change, greyed with its own reason, and never a copy: this module never learns
  the agent or status modules exist.
- **Activating a row opens its details**, by running ``steps.details`` against a context
  naming exactly that row's step.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.progression import Progression, progression
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import EntityActivity, follow_entity_tabs, follow_project
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
from dplanner.framework.segmented import Segmented
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState
from dplanner.modules.progression.view import ALL, GROUPS, StatusTable, needing_a_person
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECTION_GAP

MODULE_ID = "progression"
PROGRESSION_KIND = "progression"

FILTERS = (
    (ALL, "All", "Everything that needs a person, then what is waiting"),
    *((group.key, group.label, group.heading) for group in GROUPS),
)
NO_STEPS = "No steps yet."
NOTHING_NEEDED = "Nothing needs you right now."


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
    # The status claims, as answers — a wait read done once it is over. Wired by the
    # composition root from the status aspect's Qt-free reader; the honest default is a
    # build where nothing is claimed.
    status_for: Callable[[Step], str] = field(default=_pending)
    # Whether a step is work at all: a wait is not, and is on no row and in no count.
    counts_as_work: Callable[[Step], bool] = field(default=lambda _step: True)
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


class ProgressionActivity(EntityActivity):
    """One project's Step statuses."""

    def __init__(self, deps: ProgressionDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id
        self._filter = ALL
        self._found: Progression | None = None
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

        self.table = StatusTable(
            key_of=deps.key_of,
            glyph_of=deps.glyph_of,
            milestone_badge=deps.milestone_badge,
            parent=page,
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_row_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._widget = page
        library = self._product
        # After a quiet spell, not per signal: every row is rebuilt.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            # This project only, and no prose: the table reads statuses, titles and links.
            follow_project(
                library,
                self.project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.structure_changed,
                    library.edges_changed,
                    library.field_changed,
                    library.module_data_changed,
                ),
            ),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(PROGRESSION_KIND, self.project_id)

    @property
    def title(self) -> str:
        """The project, and how many rows need a person — said only when some do."""
        name = self._project().title or "Untitled project"
        count = f" ({self._needing})" if self._needing else ""
        return f"{name} — Step statuses{count}"

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

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        self._found = progression(
            self._product, self._project(), deps.status_for, deps.counts_as_work
        )
        self._show()
        needing = needing_a_person(self._found)
        if needing != self._needing:
            self._needing = needing
            deps.tabs.set_tab_title(self, self.title)

    def _show(self) -> None:
        found = self._found
        if found is None:
            return
        before = self.table.picked()
        self.table.show_rows(found, self._filter)
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


class ProgressionModule:
    id = MODULE_ID

    def __init__(self, deps: ProgressionDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(PROGRESSION_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProgressionActivity:
            assert target is not None
            return ProgressionActivity(deps, target)

        deps.tabs.register_factory(PROGRESSION_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="progression.open",
                label="Show Step Stat&uses",
                menu="Project",
                group="open",
                in_menus=False,  # Its seat is the project's row in the index — menus.py.
                order=30,
                tip="What needs a person right now: blocked, to merge, to review, to start",
                state=self._on_a_project,
                run=self._open,
            )
        )
        # The same verb placed in the Step menu, beside Show Order's mirror there.
        # palette=False: one palette entry.
        deps.actions.register(
            ActionSpec(
                id="progression.open_step",
                label="Show Step Stat&uses",
                menu="Step",
                group="surfaces",
                order=30,
                tip="What needs a person right now: blocked, to merge, to review, to start",
                palette=False,
                state=self._on_a_project,
                run=self._open,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            ProgressionActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)
