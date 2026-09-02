"""The status aspect, in the running application: a Status submenu, no tab.

One enum does not earn a tab in the step detail panel. What it earns is a verb per state —
checkable actions under one submenu — which lands in the canvas right-click, the order
table's, the menu bar and the command palette at once, because that is what registering an
:class:`ActionSpec` means here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import focused_step
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.modules.step_status.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    STATUSES,
    read,
    write,
)


@dataclass(frozen=True)
class StepStatusDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry


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
                    label=status.replace("-", " ").title(),
                    menu="Step",
                    group="classify",
                    submenu="Status",
                    # The 200s: Status is the second child menu of the classify band, and a
                    # child menu sits at its first entry's order. See dplanner/menus.py.
                    order=200 + order * 10,
                    tip=f"Mark this step {status.replace('-', ' ')}",
                    state=self._current(status),
                    run=self._setter(status),
                )
            )

    def _current(self, status: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            step = focused_step(context, self._deps.library)
            if step is None:
                return DISABLED
            return ActionState(checked=read(step) == status)

        return state

    def _setter(self, status: str) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            step = focused_step(context, self._deps.library)
            if step is None or read(step) == status:
                return
            self._deps.undo.push(
                SetModuleDataCommand(step.id, MODULE_ID, write(status), label="Set Status")
            )

        return run
