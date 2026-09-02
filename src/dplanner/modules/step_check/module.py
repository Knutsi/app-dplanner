"""The check aspect, in the running application: a Type toggle, and nothing else.

The *Covers* tab belongs to the module that owns tests — it is a list of tests, and a tab
that renders one is testing's business, not this package's. That keeps the wiring
one-directional: ``testing`` is handed a predicate that reads this aspect, and nothing here
has to know that module exists.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.undo import UndoService
from dplanner.modules.step_check.aspect import DATA_FORMAT, MODULE_ID, SPEC, read, write
from dplanner.theme.icons import shield_icon


@dataclass(frozen=True)
class StepCheckDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry


class StepCheckModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepCheckDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            aspect_toggle(
                id="check.toggle",
                label=SPEC.label,
                order=60,
                module_id=MODULE_ID,
                library=self._deps.library,
                undo=self._deps.undo,
                enabled=read,
                fresh=lambda _step, _project: write(True),
                icon=shield_icon,
                tip="Gather every test this step waits on, so a run can be scoped to it",
            )
        )
