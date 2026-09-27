"""The status aspect, in the running application: a Status submenu, no tab.

One enum does not earn a tab in the step detail panel. What it earns is a verb per state —
checkable actions under one submenu — which lands in the canvas right-click, the order
table's, the menu bar and the command palette at once, because that is what registering an
:class:`ActionSpec` means here.

**A verb acts on every chosen step** (``chosen_steps``, the definition Delete and Run Agent
read), as one undo step: a lasso on the canvas, or the rows ticked in the Step statuses
tab, all move at once. It reads as checked only when every one of them already stands
there, and a wait among them greys it, saying why — a wait has no status to set.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QIcon

from dplanner.core.clock import Clock
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step
from dplanner.domain.progression import (
    BLOCKED,
    DONE,
    IN_PROGRESS,
    READY_FOR_REVIEW,
    READY_TO_MERGE,
    phrase,
)
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.undo import UndoService
from dplanner.modules.step_status.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    NO_STATUS_ON_A_WAIT,
    PENDING,
    STATUSES,
    label,
    read,
    write,
)
from dplanner.theme.icons import (
    check_icon,
    eye_icon,
    play_icon,
    pull_request_icon,
    step_icon,
    stop_icon,
)

# One glyph per state, so the submenu, the palette and a strip that seats a verb agree.
GLYPHS: dict[str, Callable[[QColor], QIcon]] = {
    PENDING: step_icon,
    IN_PROGRESS: play_icon,
    READY_FOR_REVIEW: eye_icon,
    READY_TO_MERGE: pull_request_icon,
    DONE: check_icon,
    BLOCKED: stop_icon,
}


@dataclass(frozen=True)
class StepStatusDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    clock: Clock  # The day a status change is stamped with.
    # A wait has no status of its own — it is over when its day comes — so the verbs grey
    # on one. The composition root knows what marks a wait.
    is_wait: Callable[[Step], bool] = field(default=lambda _step: False)


class StepStatusModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepStatusDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        for order, status in enumerate(STATUSES, start=1):
            self._deps.actions.register(
                ActionSpec(
                    id=f"status.{status}",
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

    def _current(self, status: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            steps = self._chosen(context)
            if not steps:
                return DISABLED
            if any(self._deps.is_wait(step) for step in steps):
                return ActionState(enabled=False, label=f"{label(status)} — {NO_STATUS_ON_A_WAIT}")
            return ActionState(checked=all(read(step) == status for step in steps))

        return state

    def _setter(self, status: str) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            steps = self._chosen(context)
            if any(self._deps.is_wait(step) for step in steps):
                return
            today = self._deps.clock.today()
            with self._deps.undo.gesture("Set Status"):
                for step in steps:
                    if read(step) == status:
                        continue
                    entry = write(status, today=today, previous=step.module_data.get(MODULE_ID))
                    self._deps.undo.push(
                        SetModuleDataCommand(step.id, MODULE_ID, entry, label="Set Status")
                    )

        return run
