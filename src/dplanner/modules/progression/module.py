"""Progression mode: the execution surface for a project — as a tab beside its graph.

The graph plans the work; this board is for the weeks the work is *happening*: how far
along the project is, what is running or stuck, what can be launched right now and what
one more finish would free. The walk itself is the domain's (``domain/progression.py``)
— this module renders it and adds nothing to the model, so the tab, ``dplanner
progression show`` and ``--json`` can never disagree.

Four seams, all established elsewhere in this application:

- **Statuses and estimates arrive as functions** (``status_for``, ``days_for``), wired by
  the composition root from the aspects' Qt-free readers — this module never learns what
  either is stored as.
- **Selecting a card publishes the selection scope**, so the Step menu's verbs target it.
- **Activating one opens its details**, by running ``steps.details`` against a context
  naming exactly that card's step — the same seam the Run button already uses.
- **Run Agent arrives as a state and a menu** (``agent_state``, ``agent_menu``), closed
  over the real action and the Step menu's own Run Agent child by the composition root.
  The Ready lane's *Run N Agents* button renders the gate's answer over the ticked steps
  — a disabled one wears the reason — and drops that child menu down, so the board
  offers what the menu offers and this module never learns the agent module exists.
  ``None`` is a build without an agent: the button and the ticks are absent, not greyed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.progression import estimated_progress, progression
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
from dplanner.framework.widgets import centered_column
from dplanner.modules.progression.view import BOARD_MAX_WIDTH, ProgressionBoard, RunControl

MODULE_ID = "progression"
PROGRESSION_KIND = "progression"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12


def _pending(_step: Step) -> str:
    return "pending"


def _no_days(_step: Step) -> float | None:
    return None


def _no_badge(_step_id: StepId) -> QIcon | None:
    return None


@dataclass(frozen=True)
class ProgressionDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    # The stored status claims, as answers. Wired by the composition root from the status
    # aspect's Qt-free reader; the honest default is a build where nothing is claimed.
    status_for: Callable[[Step], str] = field(default=_pending)
    # A step's estimated days, for the weighted header line. Same seam, same owner rule.
    days_for: Callable[[Step], float | None] = field(default=_no_days)
    # The Run Agent gate, closed over the real action, and the fill of the Step menu's
    # Run Agent child — the profiles, then Manage Agent Profiles… — which the Ready lane's
    # button drops down. None is a build without an agent: the button is absent from the
    # board, not disabled.
    agent_state: Callable[[Context], ActionState] | None = None
    agent_menu: Callable[[QMenu], None] | None = None
    # A milestone's key and its own shade of the project's colour map, or None for a step
    # that is not one — the badge its card leads with. Wired by the composition root: which
    # map a project uses is one module's assumption and the key is another's letter.
    milestone_badge: Callable[[StepId], QIcon | None] = field(default=_no_badge)


class ProgressionActivity(EntityActivity):
    """One project's execution board."""

    def __init__(self, deps: ProgressionDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id

        # The caption, note and board share one column capped at a readable measure —
        # three lanes say nothing more by being wider, so past that the column centres.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Progression", content)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        note = QLabel(
            "What can be launched right now, from the graph and the stored statuses. Ready "
            "steps rank by what finishing them unblocks; Up next is one finish away.",
            content,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(BLOCK_GAP)

        self.board = ProgressionBoard(
            select=self._publish,
            details=self._open_details,
            menu=self._on_context_menu,
            run_control=self._run_control,
            milestone_badge=deps.milestone_badge,
            parent=content,
        )
        layout.addWidget(self.board, 1)

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        outer.addWidget(centered_column(content, BOARD_MAX_WIDTH))

        self._widget = page
        library = self._product
        # After a quiet spell, not per signal: every card is rebuilt.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self._unsubscribes = [
            # This project only, and no prose: the board reads statuses and titles.
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
        return f"{self._project().title or 'Untitled project'} — Progression"

    @property
    def widget(self) -> QWidget:
        return self._widget

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
        progress = progression(self._product, self._project(), self._deps.status_for)
        self.board.show_progress(progress, estimated_progress(progress, self._deps.days_for))

    def _publish(self, step_id: StepId | None) -> None:
        self._publish_all([] if step_id is None else [step_id])

    def _publish_all(self, step_ids: list[StepId]) -> None:
        self.publish_selection(_nodes(step_ids))

    def _step_context(self, step_id: StepId) -> Context:
        """A context naming exactly this card's step — what a verb run from the card is
        handed, so it acts on the card even when this pane is not the active one and
        its publish was suppressed."""
        return Context({SCOPE_SELECTION: _nodes([step_id])})

    def _open_details(self, step_id: StepId) -> None:
        # Select first, so the window agrees about what the dialog is showing; then run the
        # verb against this card's own step, the same way the Run button does.
        self._publish(step_id)
        self._deps.actions.run("steps.details", self._step_context(step_id))

    def _run_control(self, step_ids: list[StepId]) -> RunControl | None:
        """The Run N Agents button over the ticked steps: the gate's own answer, and the
        Step menu's Run Agent child as its dropdown.

        The gate is asked against a context naming exactly the ticked steps, so the face
        counts what is ticked whatever the window's selection is; opening the menu then
        publishes them, because its entries — like every presenter — act on the context
        the user has now. A press on the board makes this pane the active one first.
        """
        deps = self._deps
        if deps.agent_state is None or deps.agent_menu is None:
            return None  # A build without an agent: the capability is absent, not greyed.
        agent_menu = deps.agent_menu
        count = len(step_ids)
        label = f"Run {count} Agent{'' if count == 1 else 's'}" if count else "Run Agents"
        if not count:
            reason = "Tick the ready steps to run, then pick an agent and a terminal"
            return RunControl(label, False, reason, agent_menu)
        state = deps.agent_state(Context({SCOPE_SELECTION: _nodes(step_ids)}))
        reason = "Pick an agent and a terminal"
        if not state.enabled and state.label:
            reason = state.label  # The gate's own words: a disabled face teaches why.

        def fill(menu: QMenu) -> None:
            self._publish_all(step_ids)
            agent_menu(menu)

        return RunControl(label, state.enabled, reason, fill)

    def _on_context_menu(self, _step_id: StepId, position: QPoint) -> None:
        # The card published its step on the press, so the menu reads the same context
        # every other presenter does.
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.board)
        menu.exec(position)


def _nodes(step_ids: list[StepId]) -> tuple[ContextNode, ...]:
    return tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)


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
                label="Show &Progression",
                menu="Project",
                group="open",
                order=30,
                tip="What can be launched right now, and how far along the project is",
                state=self._on_a_project,
                run=self._open,
            )
        )
        # The same verb placed in the Step menu, beside Show Order's mirror there.
        # palette=False: one palette entry.
        deps.actions.register(
            ActionSpec(
                id="progression.open_step",
                label="Show &Progression",
                menu="Step",
                group="open",
                order=30,
                tip="What can be launched right now, and how far along the project is",
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
