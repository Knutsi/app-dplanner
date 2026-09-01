"""The feature aspect, in the running application: a Type toggle, and nothing else.

The tab that shows what a feature gathers belongs to the module that owns tests — it is a
list of tests, and a tab that renders one is testing's business, not this package's. That is
the same wiring the check aspect uses: ``testing`` is handed predicates that read this
aspect, and nothing here has to know that module exists.
"""

from dataclasses import dataclass

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.modules.step_feature.aspect import DATA_FORMAT, MODULE_ID, SPEC, read, write


@dataclass(frozen=True)
class StepFeatureDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry


class StepFeatureModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepFeatureDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="feature.toggle",
                label=SPEC.label,
                menu="Step",
                group="classify",
                submenu="Type",
                order=20,
                tip="Collect the work and tests behind this step, up to the previous feature",
                state=self._current,
                run=self._toggle,
            )
        )

    def _current(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=read(step))

    def _toggle(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        # No confirmation on the way out: a feature stores nothing, so clearing loses nothing.
        on = not read(step)
        self._deps.undo.push(
            SetModuleDataCommand(
                step.id,
                MODULE_ID,
                write(on),
                label="Mark as Feature" if on else "Clear Feature",
            )
        )

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
