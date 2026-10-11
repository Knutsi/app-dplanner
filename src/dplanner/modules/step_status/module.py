"""The status aspect, in the running application: a Status submenu, no tab.

One enum does not earn a tab in the step detail panel. What it earns is a verb per state —
checkable actions under one submenu — which lands in the canvas right-click, the order
table's, the menu bar and the command palette at once, because that is what registering an
:class:`ActionSpec` means here.

**A verb acts on every chosen step** (``chosen_steps``, the definition Delete and Run Agent
read), as one undo step: a lasso on the canvas, or the rows ticked in the Step statuses
tab, all move at once. It reads as checked only when every one of them already stands
there, and a wait among them greys it, saying why — a wait has no status to set.

**The verb is the workflow's, not this module's.** Whether it applies and what it writes come
from ``workflows.py``, the same calls ``dplanner status set`` makes; the window's actor is
the director, so a status that says the work stopped ends the agent's claim on the step —
**only once that status is on disk**, as the CLI does: a claim ended over a status that never
reached the file would tell another reader the work stopped when the plan says it did not.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QColor, QIcon

from dplanner.core.clock import Clock
from dplanner.domain.commands import CompositeCommand
from dplanner.domain.model import Library, Step
from dplanner.domain.workflow import EndClaim, FollowUp, Person, Release
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.notices import Notice
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.undo import UndoService
from dplanner.framework.window import NoticeHost
from dplanner.modules.step_status.workflows import LABEL, STOPPED, StatusWorkflow, perform
from dplanner.planning.status import DATA_FORMAT, MODULE_ID, Status, label, phrase, stored
from dplanner.theme.icons import (
    check_icon,
    eye_icon,
    play_icon,
    pull_request_icon,
    step_icon,
    stop_icon,
)

# One glyph per state, so the submenu, the palette and a strip that seats a verb agree.
GLYPHS: dict[Status, Callable[[QColor], QIcon]] = {
    Status.PENDING: step_icon,
    Status.IN_PROGRESS: play_icon,
    Status.READY_FOR_REVIEW: eye_icon,
    Status.READY_TO_MERGE: pull_request_icon,
    Status.DONE: check_icon,
    Status.BLOCKED: stop_icon,
}


@dataclass(frozen=True)
class StepStatusDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    clock: Clock  # The day a status change is stamped with.
    workflow: StatusWorkflow
    end_claim: Callable[[EndClaim], bool]  # The at-work board's; answers whether one stood.
    release: Callable[[Release], bool]  # Out of its squad's claim; answers whether one held it.
    notices: NoticeHost  # Where a claim that could not be ended stands, with a retry.
    flush: Callable[[], bool]  # Autosave's flush now: whether everything is on disk after it.


NOTICE_ID = "step_status.unreleased"


class StepStatusModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepStatusDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        for order, status in enumerate(Status, start=1):
            self._deps.actions.register(
                ActionSpec(
                    id=f"status.{status.value}",
                    label=label(status),
                    menu="Step",
                    group="track",
                    submenu="Status",
                    # The 200s: Status leads the track band, before Estimate's 400s, and a
                    # child menu sits at its first entry's order. See dplanner/menus.py.
                    order=200 + order * 10,
                    tip=f"Mark this step {phrase(status)}",
                    icon=GLYPHS[status],
                    state=self._current(status),
                    run=self._setter(status),
                )
            )

    def _chosen(self, context: Context) -> list[Step]:
        library = self._deps.library
        return [library.step(step_id) for step_id in chosen_steps(context, library)]

    def _current(self, status: Status) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            steps = self._chosen(context)
            if not steps:
                return DISABLED
            if why := self._deps.workflow.refusal(steps, status, Person()):
                return ActionState(enabled=False, label=f"{label(status)} — {why}")
            return ActionState(checked=all(stored(step) is status for step in steps))

        return state

    def _setter(self, status: Status) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            steps = self._chosen(context)
            if self._deps.workflow.refusal(steps, status, Person()):
                return
            today = self._deps.clock.today()
            library = self._deps.library
            changes = [
                self._deps.workflow.set_status(library, step, status, actor=Person(), today=today)[
                    0
                ]
                for step in steps
            ]
            # One composite, not a gesture of pushes: it is all-or-nothing on the way in, so
            # a refusal part way leaves no step moved and no claim ended.
            commands = [change.command for change in changes if change.command is not None]
            if commands:
                self._deps.undo.push(CompositeCommand(LABEL, commands))
            self._release([each for change in changes for each in change.follow_ups])

        return run

    def _release(self, follow_ups: list[FollowUp]) -> None:
        """End the claims a stopped status owes, each on its own, once the statuses are on
        disk. Any that could not be ended — or all of them, while the save is held back or
        refused — stand on a notice with a retry: the statuses are true, and are not undone
        for an effect."""
        if not follow_ups:
            return
        if not self._deps.flush():
            self._owed(
                follow_ups,
                f"the plan is not saved yet, so {len(follow_ups)} agent claim(s) still stand",
            )
            return
        follow_ups = [each for each in follow_ups if self._still_stopped(each)]
        failed = perform(follow_ups, self._deps.end_claim, self._deps.release).failed
        if not failed:
            self._deps.notices.clear_notice(NOTICE_ID)
            return
        self._owed(
            [each for each, _why in failed],
            f"{len(failed)} agent claim(s) could not be ended: {failed[0][1]}",
        )

    def _still_stopped(self, follow_up: FollowUp) -> bool:
        """Whether the saved plan still says the work on the follow-up's step stopped. A
        retry comes later than the status that owed it — an undo or another writer may have
        taken that status back, and then the claim is no longer owed."""
        library = self._deps.library
        return library.has(follow_up.step) and stored(library.step(follow_up.step)) in STOPPED

    def _owed(self, follow_ups: list[FollowUp], why: str) -> None:
        self._deps.notices.show_notice(
            Notice(
                id=NOTICE_ID,
                words=f"The status is set, but {why}",
                tone="error",
                action="Retry",
                tip="Save the plan and end the claims again",
                act=lambda: self._release(follow_ups),
            )
        )
