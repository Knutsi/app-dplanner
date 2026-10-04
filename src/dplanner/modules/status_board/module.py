"""Step statuses and the Control Centre: what needs a person right now — in one project, as a
tab beside its graph, or in every project at once.

The graph plans the work; these tabs are for the weeks the work is *happening*, and they ask
one question: what needs me? A table answers it, grouped the way the work comes back to a
person — Blocked, Waits for you, Ready to merge, Ready for review, Ready to start — with
Waiting, what cannot start yet, last. Work an agent is doing is not listed: it needs
nobody — unless the agent waits on a person, a plan to approve or a question to answer,
which is *Waits for you* (``asks_person``, the agent-run aspect's reading). The walk
itself is the domain's (``planning/progression.py``) — this module renders it and adds
nothing to the model, so the tabs, ``dplanner progression show`` and ``--json`` can never
disagree.

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

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtGui import QIcon

from dplanner.core.clock import Clock
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    follow_project_tabs,
)
from dplanner.framework.context import (
    Context,
    ContextService,
)
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry, SurfaceSegment
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.modules.status_board.activity import (
    CONTROL_CENTRE,
    CONTROL_CENTRE_KIND,
    PROGRESSION_KIND,
    ControlCentreActivity,
    ProgressionActivity,
)
from dplanner.planning.status import Status
from dplanner.theme.icons import gauge_icon

MODULE_ID = "progression"


def _pending(_step: Step) -> Status:
    return Status.PENDING


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
    status_for: Callable[[Step], Status] = field(default=_pending)
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
    # Whether an agent works a step: a step under review that an agent takes on from there
    # is that agent's turn, not a person's, and leaves *Ready for review*.
    is_agent: Callable[[Step], bool] = field(default=lambda _step: False)
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
