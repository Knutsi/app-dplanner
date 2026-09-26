"""The order a project can be done in, as a tab beside the graph it came from.

A project is a graph, and this answers the question a graph is for: what can be started now,
and what has to wait for what. The walk itself is the domain's — this module renders it and
adds nothing to the model.

**Nothing here is stored.** The order is recomputed whenever the graph changes, which is what
makes it impossible for it to disagree with the graph. See ``domain/ordering.py``.

Three seams, all established elsewhere in this application:

- **Selecting a step publishes the selection scope**, so the Step menu's verbs target it —
  this view never learns that those verbs exist.
- **Activating one opens its details**, by running ``steps.details`` against a context
  naming exactly that row's step — the same registry path the menus use, so whoever owns
  the dialog is not this module's business.
- **The estimates arrive as an answer, not as data to interpret.** Whoever owns them hands
  over the order already carrying each step's days. This module never learns what an
  estimate is stored as, and there is a working default for a build with nobody to ask.

What the page says under its caption is the **volume**: the estimated days the order comes
to, over how many steps, and how many nobody has sized — the sentence ``dplanner order
show``, ``estimate rollup`` and the Estimates tab all print (``domain/schedule.py``'s
``volume_words``). It replaced a paragraph explaining what a wave is, which is now the
caption's own info glyph, and the serial calendar the table used to run out beside it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.model import Library, NodeId, Project, ProjectId, Step, StepId
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.schedule import Scheduled, schedule, volume, volume_words
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
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.step_order.cli import wave_label
from dplanner.modules.step_order.export import order_rows
from dplanner.modules.step_order.view import OrderTable
from dplanner.theme.icons import list_icon

MODULE_ID = "step_order"
ORDER_KIND = "order"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
SWITCH_GAP = 16


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def _no_milestone(_step_id: StepId) -> str:
    return ""


def _no_color(_step_id: StepId) -> str:
    return ""


def _no_icons(_step_id: StepId) -> tuple[str, ...]:
    return ()


def _unscheduled(_project_id: ProjectId, order: Sequence[Placed]) -> list[Scheduled]:
    """Nobody in this build knows what a step costs: every row, no days, no dates.

    The honest empty answer is the domain function itself, asked a question with no answer —
    which is why the table needs no branch for a build without estimates.
    """
    return schedule(order, lambda _step: None, date.today())


@dataclass(frozen=True)
class StepOrderDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    parent: QWidget  # The CSV export's file dialog needs a window to parent on.
    debounce: DebounceService
    tabs: TabHost
    # What the aspect modules have to say about a step, one short phrase each.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)
    # The order carrying what each step costs and when it lands. Wired by the composition
    # root; this module never learns what an estimate is.
    step_schedule: Callable[[ProjectId, Sequence[Placed]], list[Scheduled]] = field(
        default=_unscheduled
    )
    # The label of the milestone a step is, "" otherwise. Wired by the composition root;
    # this module never learns who owns milestones.
    milestone_label: Callable[[StepId], str] = field(default=_no_milestone)
    # What kind of thing a step is, in the canvas medallions' vocabulary ("tag", "spark"),
    # so the title column wears the same marks the graph does. Wired by the composition
    # root; this module never learns which aspects the kinds stand for.
    step_icons: Callable[[StepId], tuple[str, ...]] = field(default=_no_icons)
    # A milestone's own shade of the project's colour map, and the key its row wears as
    # a badge. Both from the composition root: which map a project uses is one module's
    # assumption and a step's key is another's letter, and this one learns neither.
    milestone_color: Callable[[StepId], str] = field(default=_no_color)
    step_key: Callable[[StepId], str] = field(default=_no_color)
    # Whether a step is work at all: a wait is not, and is no part of the volume.
    counts_as_work: Callable[[Step], bool] = field(default=lambda _step: True)


class OrderActivity(EntityActivity):
    """One project's steps, in waves."""

    def __init__(self, deps: StepOrderDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        # The caption row carries one quiet Export button whose arrow renders File ▸ Export
        # — the same entries, never a copy — so the exports are found where the table is.
        # What a wave is stands behind the caption's info glyph rather than in a paragraph
        # under it (DESIGN.md's *Words*): it is a convention, and a convention is read once.
        head = QHBoxLayout()
        layout.addLayout(head)
        head.addWidget(
            captioned(
                "Order",
                page,
                hint="Steps in an order that never puts one before what it waits on. "
                "Everything in Wave 1 can be started now.",
            ),
            1,
        )
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("report.html",),
            {"report.html": "Export"},
            page,
            menus={"report.html": ("File", "Export")},
        )
        head.addWidget(self.toolbar)
        self.updating = UpdatingIndicator(page)
        head.addWidget(self.updating)

        # A remark that changes with the data, which is what #InspectorNote is for.
        self.volume = note("", page)
        layout.addWidget(self.volume)
        layout.addSpacing(BLOCK_GAP)

        # Two perspectives on one order: the work steps, the features, or both — the
        # milestones are the fixed points either way, so unticking both leaves the roadmap.
        switches = QWidget(page)
        switch_row = QHBoxLayout(switches)
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(SWITCH_GAP)
        self.show_steps = QCheckBox("Steps", switches)
        self.show_features = QCheckBox("Features", switches)
        for switch in (self.show_steps, self.show_features):
            switch.setChecked(True)
            switch.toggled.connect(self._on_kinds)
            switch_row.addWidget(switch)
        switch_row.addStretch(1)
        layout.addWidget(switches)
        layout.addSpacing(CAPTION_GAP)

        self.table = OrderTable(
            wave_label,
            deps.step_aspects,
            deps.milestone_label,
            deps.step_icons,
            deps.milestone_color,
            deps.step_key,
            page,
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_activated)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, 1)
        # One swap, and the table is what it stands in for (DESIGN.md's *Words*).
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._widget = page
        # After a quiet spell, not per signal: the table is rebuilt row by row.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            # Every signal, this project only. The title column's kind icons read prose
            # presence (an agent instruction), so a text edit can change what a row wears.
            follow_project(self._product, self.project_id, self._refresh_soon.trigger),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(ORDER_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Order"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._publish(self.table.selected_step())

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.toolbar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        order = placed(self._product, self._project())
        scheduled = self._deps.step_schedule(self.project_id, order)
        self.table.show_order(scheduled)
        days = {row.place.step.id: row.days for row in scheduled}
        steps = [row.place.step for row in scheduled]
        said = volume(steps, lambda step: days[step.id], self._deps.counts_as_work)
        self.volume.setText(volume_words(*said))
        self.volume.setVisible(bool(scheduled))
        self.empty.say("" if scheduled else "Steps appear here in the order they can be done.")

    def _on_kinds(self) -> None:
        self.table.show_kinds(
            steps=self.show_steps.isChecked(), features=self.show_features.isChecked()
        )

    def _publish(self, step_id: StepId | None) -> None:
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self.publish_selection(nodes)

    def _on_selection(self) -> None:
        self._publish(self.table.selected_step())

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            # Against a context naming exactly this row's step, not the service's — the
            # double-click means the row under it even if a publish was suppressed.
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        row = self.table.rowAt(position.y())
        if self.table.step_at(row) is None:
            return
        self.table.selectRow(row)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))


class StepOrderModule:
    id = MODULE_ID

    def __init__(self, deps: StepOrderDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(ORDER_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> OrderActivity:
            assert target is not None
            return OrderActivity(deps, target)

        deps.tabs.register_factory(ORDER_KIND, factory)
        # The Project side is the index tree's "Order" row now; the verb's menu seat is
        # the Step menu, so the canvas right-click still offers it — and the canvas
        # toolbar reaches the same id through the registry.
        deps.actions.register(
            ActionSpec(
                id="order.open",
                label="Show &Order",
                menu="Step",
                group="open",
                order=20,
                icon=list_icon,
                tip="What can be started now, and what waits for what",
                state=self._on_a_project,
                run=self._open,
            )
        )
        # File ▸ Export ▸ Order List: the same rows the table shows, as a CSV a spreadsheet
        # can compute with. The submenu leaves room for other features' exports beside it.
        deps.actions.register(
            ActionSpec(
                id="order.export",
                label="&Order List (CSV)…",
                menu="File",
                group="export",
                submenu="Export",
                order=10,
                tip="Write the focused project's order to a CSV file",
                state=self._on_a_project,
                run=self._export,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            OrderActivity,
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

    def _export(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None:
            return
        deps = self._deps
        project = deps.library.project(project_id)
        order = placed(deps.library, project)
        rows = order_rows(
            deps.step_schedule(project_id, order), deps.step_aspects, deps.milestone_label
        )
        suggested = f"{project.title or 'Untitled project'} order.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, "Export Order List", str(Path.home() / suggested), "CSV files (*.csv)"
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        write_csv(path, rows)
