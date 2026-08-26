"""The order a project can be done in, as a tab beside the graph it came from.

A project is a graph, and this answers the question a graph is for: what can be started now,
and what has to wait for what. The walk itself is the domain's — this module renders it and
adds nothing to the model.

**Nothing here is stored.** The order is recomputed whenever the graph changes, which is what
makes it impossible for it to disagree with the graph. See ``domain/ordering.py``.

Three seams, all established elsewhere in this application:

- **Selecting a step publishes the selection scope**, so the Step menu's verbs target it —
  this view never learns that those verbs exist.
- **Activating one reveals it in the graph**, through a callback the composition root
  supplies. This module does not import the project editor, and the project editor does not
  know this view exists.
- **The schedule arrives as an answer, not as data to interpret.** Whoever owns estimates
  hands over the order already carrying days and dates, and lends the widget that sets the
  start date. This module never learns what an estimate is stored as, and there is a working
  default for a build with nobody to ask.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import NodeId, Product, Project, ProjectId, StepId
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.schedule import Scheduled, schedule
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    ENABLED,
    HIDDEN,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.tabs import TabHost
from dplanner.modules.step_order.cli import wave_label
from dplanner.modules.step_order.view import OrderTable

MODULE_ID = "step_order"
ORDER_KIND = "order"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12


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


def _no_reveal(_step_id: StepId) -> None:
    pass


def _unscheduled(_project_id: ProjectId, order: Sequence[Placed]) -> list[Scheduled]:
    """Nobody in this build knows what a step costs: every row, no days, no dates.

    The honest empty answer is the domain function itself, asked a question with no answer —
    which is why the table needs no branch for a build without estimates.
    """
    return schedule(order, lambda _step: None)


@dataclass(frozen=True)
class StepOrderDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    parent: QWidget
    # Show a step in whatever edits graphs. Wired by the composition root; this module never
    # learns that a graph editor exists.
    reveal_step: Callable[[StepId], None] = field(default=_no_reveal)
    # What the aspect modules have to say about a step, one short phrase each.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)
    # The order carrying what each step costs and when it lands. Wired by the composition
    # root; this module never learns what an estimate is.
    step_schedule: Callable[[ProjectId, Sequence[Placed]], list[Scheduled]] = field(
        default=_unscheduled
    )
    # The widget that sets the date the schedule counts from. None is a legitimate build.
    start_bar: Callable[[ProjectId, QWidget], StartBar] | None = None


class OrderActivity(ActivityBase):
    """One project's steps, in waves."""

    def __init__(self, deps: StepOrderDeps, project_id: NodeId) -> None:
        self._deps = deps
        self._product = deps.product
        self.project_id = project_id
        # There is one selection scope and there can be several panes on screen. Only the
        # pane the user is in may write to it — see CLAUDE.md's "only the active pane speaks
        # for the user". This table sits beside the graph often, so it matters here.
        self._is_active = False

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Order", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

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

        self.table = OrderTable(wave_label, deps.step_aspects, page)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_activated)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, 1)

        self._widget = page
        self._unsubscribes = [
            self._product.structure_changed.connect(lambda *_a: self._refresh()),
            self._product.edges_changed.connect(lambda *_a: self._refresh()),
            self._product.field_changed.connect(lambda *_a: self._refresh()),
            self._product.module_data_changed.connect(lambda *_a: self._refresh()),
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
        self._is_active = True
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )
        self._publish(self.table.selected_step())

    def on_deactivated(self) -> None:
        self._is_active = False

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        if self.start_bar is not None:
            self.start_bar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        order = placed(self._product, self._project())
        self.table.show_order(self._deps.step_schedule(self.project_id, order))

    def _publish(self, step_id: StepId | None) -> None:
        if not self._is_active:
            return  # See _is_active: a background pane does not speak for the user.
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self._deps.context.set_scope(SCOPE_SELECTION, nodes)

    def _on_selection(self) -> None:
        self._publish(self.table.selected_step())

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            self._deps.reveal_step(step_id)

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

    def open(self, project_id: NodeId) -> None:
        self._deps.tabs.open(ORDER_KIND, project_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> OrderActivity:
            assert target is not None
            return OrderActivity(deps, target)

        deps.tabs.register_factory(ORDER_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="order.open",
                label="Show &Order",
                menu="Project",
                group="open",
                order=20,
                tip="What can be started now, and what waits for what",
                state=self._on_a_project,
                run=self._open,
            )
        )
        deps.product.structure_changed.connect(lambda *_a: self._close_orphan_tabs())
        deps.product.field_changed.connect(lambda *_a: self._retitle_tabs())

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.product.has(project_id):
            return HIDDEN
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)

    def _activities(self) -> list[OrderActivity]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, OrderActivity)]

    def _close_orphan_tabs(self) -> None:
        for activity in self._activities():
            if not self._deps.product.has(activity.project_id):
                self._deps.tabs.close_activity(activity)

    def _retitle_tabs(self) -> None:
        for activity in self._activities():
            if self._deps.product.has(activity.project_id):
                self._deps.tabs.set_tab_title(activity, activity.title)
