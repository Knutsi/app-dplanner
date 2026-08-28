"""Estimation, in the running application.

Two registrations and one offer. The first registration is the Estimate tab in the step
detail panel: which panel shows it, and what else is beside it, is not this module's
business. The second is the bulk Estimates activity — one tab per project for sizing many
steps in a sitting — and the ``Step ▸ Estimate Steps`` verb that opens it scoped to the
selection. The offer is the start-date bar — a widget somebody else hosts, exposed as a
``create_…`` the way ``step_properties`` exposes its panel, because a control that belongs
to *one* surface has no business in a registry.

What a step's description says, and how to show a step on a canvas, are other modules'
answers; they arrive as callbacks on the ``Deps``, wired by the composition root.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Product, ProjectId, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService, activity_uri
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.estimation.bulk import ESTIMATE_KIND, BulkEstimateActivity
from dplanner.modules.estimation.section import EstimateSection
from dplanner.modules.estimation.start_bar import StartDateBar


def _no_text(_step_id: StepId) -> str:
    return ""


def _no_reveal(_step_id: StepId) -> None:
    pass


@dataclass(frozen=True)
class EstimationDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    # A step's description: one line for a row, the full prose for its tooltip. Wired by the
    # composition root; this module never learns where a description lives.
    step_summary: Callable[[StepId], str] = field(default=_no_text)
    describe_step: Callable[[StepId], str] = field(default=_no_text)
    # Show a step in whatever edits graphs. Wired by the composition root.
    reveal_step: Callable[[StepId], None] = field(default=_no_reveal)


class EstimationModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: EstimationDeps) -> None:
        self._deps = deps

    def create_start_bar(
        self, project_id: ProjectId, parent: QWidget | None = None
    ) -> StartDateBar:
        """One project's start date, for whichever surface wants to show the schedule."""
        return StartDateBar(self._deps.product, self._deps.undo, project_id, parent)

    def open_for_steps(self, project_id: ProjectId, step_ids: Sequence[StepId] = ()) -> None:
        """Open the project's Estimates tab, scoped to ``step_ids`` (or the whole project).

        On its first open the tab is moved to the pane beside the one it was opened from,
        so the list sits next to the canvas that selected the steps. On a re-run it stays
        wherever the user has since put it — only the scope changes.
        """
        tabs = self._deps.tabs
        uri = activity_uri(ESTIMATE_KIND, project_id)
        is_new = all(activity.uri != uri for activity in tabs.activities())
        activity = tabs.open(ESTIMATE_KIND, project_id)
        if is_new:
            if tabs.can_move_right():
                tabs.move_current_right()
            elif tabs.can_move_left():
                tabs.move_current_left()
        assert isinstance(activity, BulkEstimateActivity)
        activity.set_scope(tuple(step_ids))

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=10,
                factory=lambda: EstimateSection(deps.product, deps.undo),
            )
        )

        def factory(target: str | None) -> BulkEstimateActivity:
            assert target is not None
            return BulkEstimateActivity(deps, target)

        deps.tabs.register_factory(ESTIMATE_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="estimate.open",
                label="&Estimate Steps",
                menu="Step",
                group="open",
                order=10,
                tip="Size the selected steps — or the whole project — in one list",
                state=self._can_estimate,
                run=self._open_for_context,
            )
        )
        deps.product.structure_changed.connect(lambda *_a: self._close_orphan_tabs())
        deps.product.field_changed.connect(lambda *_a: self._retitle_tabs())

    # -- the verb ------------------------------------------------------------------------------

    def _selected_steps(self, context: Context) -> list[StepId]:
        product = self._deps.product
        return [s for s in context.selected_entities("step") if product.has(s)]

    def _can_estimate(self, context: Context) -> ActionState:
        selected = self._selected_steps(context)
        if len(selected) > 1:
            return ActionState(label=f"&Estimate {len(selected)} Steps")
        if selected:
            return ENABLED
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.product.has(project_id):
            return ENABLED  # The menu-bar path: no steps picked, size the whole project.
        return DISABLED

    def _open_for_context(self, context: Context) -> None:
        selected = self._selected_steps(context)
        if selected:
            self.open_for_steps(self._deps.product.project_of(selected[0]).id, selected)
            return
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.product.has(project_id):
            self.open_for_steps(project_id)

    # -- tab upkeep ----------------------------------------------------------------------------

    def _activities(self) -> list[BulkEstimateActivity]:
        return [
            a for a in self._deps.tabs.activities() if isinstance(a, BulkEstimateActivity)
        ]

    def _close_orphan_tabs(self) -> None:
        for activity in self._activities():
            if not self._deps.product.has(activity.project_id):
                self._deps.tabs.close_activity(activity)

    def _retitle_tabs(self) -> None:
        for activity in self._activities():
            if self._deps.product.has(activity.project_id):
                self._deps.tabs.set_tab_title(activity, activity.title)
