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
- **The schedule arrives as an answer, not as data to interpret.** Whoever owns estimates
  hands over the order already carrying days and dates, and lends the widget that sets the
  start date. This module never learns what an estimate is stored as, and there is a working
  default for a build with nobody to ask.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.model import Library, NodeId, Project, ProjectId, StepId
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.schedule import Scheduled, schedule
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
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import ActionToolbar
from dplanner.modules.step_order.cli import wave_label
from dplanner.modules.step_order.export import order_rows
from dplanner.modules.step_order.view import OrderTable

MODULE_ID = "step_order"
ORDER_KIND = "order"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
SWITCH_GAP = 16


class StartBar(Protocol):
    """The control the schedule is measured from.

    Consumer-owned interface, satisfied structurally by the estimation module's start-date
    bar via the composition root — the same arrangement as the project editor's panel.
    """

    @property
    def widget(self) -> QWidget: ...

    def dispose(self) -> None: ...


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def _no_milestone(_step_id: StepId) -> str:
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
    # The widget that sets the date the schedule counts from. None is a legitimate build.
    start_bar: Callable[[ProjectId, QWidget], StartBar] | None = None
    # The label of the milestone a step is, "" otherwise. Wired by the composition root;
    # this module never learns who owns milestones.
    milestone_label: Callable[[StepId], str] = field(default=_no_milestone)
    # What kind of thing a step is, in the canvas medallions' vocabulary ("tag", "spark"),
    # so the title column wears the same marks the graph does. Wired by the composition
    # root; this module never learns which aspects the kinds stand for.
    step_icons: Callable[[StepId], tuple[str, ...]] = field(default=_no_icons)


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

        caption = QLabel("Order", page)
        caption.setObjectName("InspectorCaption")
        # The caption row carries one quiet Export button whose arrow renders File ▸ Export
        # — the same entries, never a copy — so the exports are found where the table is.
        head = QHBoxLayout()
        layout.addLayout(head)
        head.addWidget(caption)
        head.addStretch(1)
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("report.html",),
            {"report.html": "Export"},
            page,
            menus={"report.html": ("File", "Export")},
        )
        head.addWidget(self.toolbar)

        self._note = QLabel(
            "Steps in an order that never puts one before what it waits on. Everything in the "
            "first wave can be started now; the dates run them one after another, weekends "
            "skipped.",
            page,
        )
        self._note.setObjectName("InspectorNote")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        self.start_bar: StartBar | None = None
        if deps.start_bar is not None:
            self.start_bar = deps.start_bar(project_id, page)
            layout.addSpacing(BLOCK_GAP)
            layout.addWidget(self.start_bar.widget)
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
            wave_label, deps.step_aspects, deps.milestone_label, deps.step_icons, page
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_activated)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, 1)

        self._widget = page
        # After a quiet spell, not per signal: the table is rebuilt row by row.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
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
        if self.start_bar is not None:
            self.start_bar.dispose()
        self.toolbar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        order = placed(self._product, self._project())
        self.table.show_order(self._deps.step_schedule(self.project_id, order))

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
