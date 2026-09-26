"""The coverage module's Qt half: the Coverage tab and the verbs that reach it.

*Show Coverage* opens the tab on a project; *Show in Coverage* opens it standing on a
step — its feature, its milestone, or its first test; *Show Spec Passage* opens the
Specs tab washed at the passages a step reaches. Each is disabled with its reason when the step has
none, never hidden, so the canvas's right-click carries all three.
"""

from dplanner.domain.model import NodeId, StepId
from dplanner.framework.action_registry import DISABLED, ENABLED, ActionSpec, ActionState
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import Context
from dplanner.modules.coverage.activity import COVERAGE_KIND, CoverageActivity, CoverageDeps
from dplanner.modules.coverage.trace import milestone_token
from dplanner.theme.icons import coverage_icon

MODULE_ID = "coverage"

NOT_TRACED_REASON = "Show in Coverage — not a feature, a milestone or a step carrying tests"
NO_PASSAGE_REASON = "Show Spec Passage — this step reaches no spec passage"


class CoverageModule:
    id = MODULE_ID

    def __init__(self, deps: CoverageDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(COVERAGE_KIND, project_id, preview=preview)

    def _opened(self, project_id: NodeId) -> CoverageActivity | None:
        activity = self._deps.tabs.open(COVERAGE_KIND, project_id)
        return activity if isinstance(activity, CoverageActivity) else None

    def show_passage(self, project_id: NodeId, document: str, quote: str) -> None:
        """The tab, standing on one passage — the Specs tab's *Coverage* button."""
        activity = self._opened(project_id)
        if activity is not None:
            activity.focus_passage(document, quote)

    def show_step(self, step_id: StepId) -> None:
        """The tab, standing on what ``step_id`` is in the trace."""
        deps = self._deps
        if not deps.library.has(step_id):
            return
        project = deps.library.project_of(step_id)
        activity = self._opened(project.id)
        if activity is None:
            return
        item_id = self._item_for(step_id)
        if item_id is not None:
            activity.focus(item_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> CoverageActivity:
            assert target is not None
            return CoverageActivity(deps, target)

        deps.tabs.register_factory(COVERAGE_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="coverage.open",
                label="Show &Coverage",
                menu="Project",
                group="open",
                order=45,
                icon=coverage_icon,
                tip="The milestones, the features under them, the spec passages they "
                "were read from and the tests and docs that prove them — as one picture",
                state=self._on_a_project,
                run=self._open,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="coverage.show_step",
                label="Show in &Coverage",
                menu="Step",
                group="open",
                order=50,
                icon=coverage_icon,
                tip="Stand this step up in the coverage picture",
                state=self._traced,
                run=self._show_step,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="coverage.show_passage",
                label="Show Spec &Passage",
                menu="Step",
                group="open",
                order=70,
                tip="Open the spec washed at the passages this step reaches",
                state=self._has_passage,
                run=self._show_passage,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            CoverageActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    # -- states and verbs --------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.library.has(project_id):
            self.open(project_id)

    def _one_step(self, context: Context) -> StepId | None:
        step_id = context.selected_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return step_id

    def _item_for(self, step_id: StepId) -> str | None:
        deps = self._deps
        feature = deps.feature_of(step_id)
        if feature:
            return f"feature:{feature}"
        if deps.is_milestone(step_id):
            return milestone_token(step_id)
        tests = deps.tests_of(step_id)
        return f"test:{tests[0]}" if tests else None

    def _traced(self, context: Context) -> ActionState:
        step_id = self._one_step(context)
        if step_id is None or self._item_for(step_id) is None:
            return ActionState(enabled=False, label=NOT_TRACED_REASON)
        return ENABLED

    def _show_step(self, context: Context) -> None:
        step_id = self._one_step(context)
        if step_id is not None:
            self.show_step(step_id)

    def _has_passage(self, context: Context) -> ActionState:
        step_id = self._one_step(context)
        if step_id is None or not self._deps.passages_of(step_id):
            return ActionState(enabled=False, label=NO_PASSAGE_REASON)
        if self._deps.show_passages is None:
            return ActionState(visible=False)
        return ENABLED

    def _show_passage(self, context: Context) -> None:
        step_id = self._one_step(context)
        deps = self._deps
        if step_id is None or deps.show_passages is None:
            return
        passages = deps.passages_of(step_id)
        if not passages:
            return
        document, first = passages[0]
        quotes = [quote for doc, quote in passages if doc == document]
        project = deps.library.project_of(step_id)
        deps.show_passages(project.id, document, quotes, first)
