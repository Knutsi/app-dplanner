"""The order a project can be done in, as a tab beside the graph it came from.

A project is a graph, and this answers the question a graph is for: what can be started now,
and what has to wait for what. The walk itself is the domain's — this module renders it and
adds nothing to the model.

**Nothing here is stored.** The order is recomputed whenever the graph changes, which is what
makes it impossible for it to disagree with the graph. See ``domain/ordering.py``.

Two seams, both already established elsewhere in this application:

- **Selecting a step publishes the selection scope**, so the Step menu's verbs target it —
  this view never learns that those verbs exist.
- **Activating one reveals it in the graph**, through a callback the composition root
  supplies. This module does not import the project editor, and the project editor does not
  know this view exists.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import NodeId, Product, Project, StepId
from dplanner.domain.ordering import placed
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


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _no_reveal(_step_id: StepId) -> None:
    pass


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


class OrderActivity(ActivityBase):
    """One project's steps, in waves."""

    def __init__(self, deps: StepOrderDeps, project_id: NodeId) -> None:
        self._deps = deps
        self._product = deps.product
        self.project_id = project_id

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Order", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        self._note = QLabel(
            "Steps in an order that never puts one before what it waits on. "
            "Everything in the first wave can be started now.",
            page,
        )
        self._note.setObjectName("InspectorNote")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

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
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )
        self._publish(self.table.selected_step())

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        self.table.show_order(placed(self._product, self._project()))

    def _publish(self, step_id: StepId | None) -> None:
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
