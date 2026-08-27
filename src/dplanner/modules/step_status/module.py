"""The status aspect, in the running application: a Status submenu, no tab.

One enum does not earn a tab in the step detail panel. What it earns is a verb per state —
checkable actions under one submenu — which lands in the canvas right-click, the order
table's, the menu bar and the command palette at once, because that is what registering an
:class:`ActionSpec` means here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, Step
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
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
    product: Product
    undo: UndoService[Product]
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
                    group="status",
                    submenu="Status",
                    order=order * 10,
                    tip=f"Mark this step {status.replace('-', ' ')}",
                    state=self._current(status),
                    run=self._setter(status),
                )
            )

    def _current(self, status: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            step = self._focused(context)
            if step is None:
                return DISABLED
            return ActionState(checked=read(step) == status)

        return state

    def _setter(self, status: str) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            step = self._focused(context)
            if step is None or read(step) == status:
                return
            self._deps.undo.push(
                SetModuleDataCommand(step.id, MODULE_ID, write(status), label="Set Status")
            )

        return run

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.product.has(step_id):
            return None
        return self._deps.product.step(step_id)
