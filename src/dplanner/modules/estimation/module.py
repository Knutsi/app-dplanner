"""Estimation, in the running application.

Two registrations and one offer. The first registration is the Estimate block on the step
detail panel's Details tab: which host shows it, and what else is beside it, is not this
module's business. The second is the bulk Estimates activity — one tab per project for sizing many
steps in a sitting — and the ``Step ▸ Estimate Steps`` verb that opens it scoped to the
selection. The offer is the start-date bar — a widget somebody else hosts, exposed as a
``create_…`` the way ``step_properties`` exposes its panel, because a control that belongs
to *one* surface has no business in a registry.

What a step's description says, and how to show a step on a canvas, are other modules'
answers; they arrive as callbacks on the ``Deps``, wired by the composition root.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from dplanner.domain.model import Library, ProjectId, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context, ContextService, activity_uri
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import DATA_FORMAT, MODULE_ID, SPEC, enabled, write
from dplanner.modules.estimation.bulk import (
    ESTIMATE_KIND,
    FILTER_UNESTIMATED,
    BulkEstimateActivity,
)
from dplanner.modules.estimation.quick_input import FREE_LABEL, QUICK_DAYS, push_estimates
from dplanner.modules.estimation.section import EstimateSection
from dplanner.theme.icons import gauge_icon


def _no_text(_step_id: StepId) -> str:
    return ""


@dataclass(frozen=True)
class EstimationDeps:
    library: Library
    undo: UndoService[Library]
    # The step panel's Details tab — the estimate is a compact row there, not a tab.
    details: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    # A step's description: one line for a row, the full prose for its tooltip. Wired by the
    # composition root; this module never learns where a description lives.
    describe_step: Callable[[StepId], str] = field(default=_no_text)


class EstimationModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: EstimationDeps) -> None:
        self._deps = deps

    def open_for_steps(
        self,
        project_id: ProjectId,
        step_ids: Sequence[StepId] = (),
        *,
        unestimated: bool = False,
    ) -> None:
        """Open the project's Estimates tab, scoped to ``step_ids`` (or the whole project),
        showing only the unsized rows when asked — the Time tab's *Estimate missing*.

        On its first open the tab is moved to the pane beside the one it was opened from,
        so the list sits next to the canvas that selected the steps. On a re-run it stays
        wherever the user has since put it — only the scope and the filter change.
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
        if unestimated:
            activity.set_filter(FILTER_UNESTIMATED)

    def register(self) -> None:
        deps = self._deps
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=10,
                hint="Working days. A week is five.",
                factory=lambda: EstimateSection(deps.library, deps.undo),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="estimate.toggle",
                label=SPEC.label,
                order=70,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                # Absence is on, so a fresh estimate writes nothing and turning off leaves
                # the opt-out: a milestone has no work of its own.
                fresh=lambda _step, _project: write(None),
                leaving=write(None, on=False),
                icon=gauge_icon,
                tip="Size this step in working days; a milestone has no work of its own",
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
                # After the Show verbs: the step's own panel leads the group it shares.
                order=60,
                tip="Size the selected steps — or the whole project — in one list",
                state=self._can_estimate,
                run=self._open_for_context,
            )
        )
        for spec in self._size_specs():
            deps.actions.register(spec)
        follow_entity_tabs(
            deps.tabs,
            BulkEstimateActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    # -- the verb ------------------------------------------------------------------------------

    def _selected_steps(self, context: Context) -> list[StepId]:
        library = self._deps.library
        return [s for s in context.selected_entities("step") if library.has(s)]

    def _can_estimate(self, context: Context) -> ActionState:
        selected = self._selected_steps(context)
        if len(selected) > 1:
            return ActionState(label=f"&Estimate {len(selected)} Steps")
        if selected:
            return ENABLED
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.library.has(project_id):
            return ENABLED  # The menu-bar path: no steps picked, size the whole project.
        return DISABLED

    def _open_for_context(self, context: Context) -> None:
        selected = self._selected_steps(context)
        if selected:
            self.open_for_steps(self._deps.library.project_of(selected[0]).id, selected)
            return
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.library.has(project_id):
            self.open_for_steps(project_id)

    # -- the quick sizes ---------------------------------------------------------------------

    def _size_specs(self) -> list[ActionSpec]:
        """Step ▸ Estimate: the sizes a step usually is, then *no time*, then none at all —
        acting on every picked step as one undo entry. The Estimates tab drops this child menu
        from its strip, the canvas's right-click renders it, and the step panel keeps its
        chips for the one step it shows."""
        sizes: list[tuple[str, float | None, str, str]] = [
            (
                f"estimate.size_{round(days * 4)}",
                days,
                f"{label} Day" if days <= 1 else f"{label} Days",
                f"Size the picked steps at {label} working day{'' if days <= 1 else 's'}",
            )
            for days, label in QUICK_DAYS
        ]
        sizes.append(
            ("estimate.size_0", 0.0, FREE_LABEL, "Count the picked steps as sized, adding no time")
        )
        sizes.append(
            ("estimate.clear", None, "Clear Estimate", "Take the picked steps' estimates away")
        )
        return [
            ActionSpec(
                id=action_id,
                label=words,
                menu="Step",
                group="classify",
                # The 400s: Estimate is the classify band's fourth child menu. See menus.py.
                submenu="Estimate",
                order=400 + 10 * index,
                tip=tip,
                state=self._size_state(words),
                run=self._sizer(days),
            )
            for index, (action_id, days, words, tip) in enumerate(sizes)
        ]

    def _sizable(self, context: Context) -> list[StepId]:
        library = self._deps.library
        return [step for step in self._selected_steps(context) if enabled(library.step(step))]

    def _size_state(self, words: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            steps = self._sizable(context)
            if not steps:
                return ActionState(enabled=False, label=f"{words} — pick a step")
            if len(steps) > 1:
                # The count says the verb is about to act on more than the eye is on.
                return ActionState(label=f"{words} for {len(steps)} Steps")
            return ENABLED

        return state

    def _sizer(self, days: float | None) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            steps = self._sizable(context)
            if steps:
                push_estimates(self._deps.library, self._deps.undo, steps, days)

        return run
