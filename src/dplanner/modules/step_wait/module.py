"""The wait aspect, in the running application: a Type toggle and a Details block.

Step ▸ Type ▸ Wait turns a step into a wait of one working day — or brings back the wait the
shelf kept — and the *Wait* template turns the estimate and the description off with it,
since a wait carries neither. How long it holds is edited in the block on its Details tab,
until a day or for working days. *Insert Wait Before* (``W`` on the canvas) puts a wait in front
of a step as one undo step — the composition root births it through the graph editor.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from dplanner.domain.model import Library, StepId
from dplanner.domain.schedule import Wait
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.step_selection import focused_step
from dplanner.framework.undo import UndoService
from dplanner.modules.step_wait.aspect import DATA_FORMAT, MODULE_ID, SPEC, is_wait, write
from dplanner.modules.step_wait.section import WaitSection
from dplanner.theme.icons import clock_icon


@dataclass(frozen=True)
class StepWaitDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    details: InspectorSectionRegistry
    today: Callable[[], date]  # The day a wait until a date is offered from.
    # A wait put in front of a step, which then waits on it — born where the step is drawn,
    # which is the graph editor's to know. None is a build with no canvas to place it on.
    insert_before: Callable[[StepId], None] | None = None


class StepWaitModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepWaitDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=12,  # Where the estimate (10) would be: a wait's size is how long.
                hint="How long this step holds what requires it: until a day, or for working days.",
                factory=lambda: WaitSection(deps.library, deps.undo, deps.today),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and is_wait(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="wait.toggle",
                label=SPEC.label,
                order=65,  # A kind, after Check (60) and before the facets (70 on).
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=is_wait,
                fresh=lambda _step, _project: write(Wait(days=1.0)),
                icon=clock_icon,
                tip="Make this step a wait: it holds what requires it until a day, or for "
                "working days, and is no work",
            )
        )
        insert = deps.insert_before
        if insert is not None:

            def state(context: Context) -> ActionState:
                return DISABLED if focused_step(context, deps.library) is None else ActionState()

            def run(context: Context) -> None:
                step = focused_step(context, deps.library)
                if step is not None:
                    insert(step.id)

            deps.actions.register(
                ActionSpec(
                    id="wait.insert_before",
                    label="Insert &Wait Before",
                    menu="Step",
                    group="edit",
                    order=15,  # Beside New (10): a step born, for this one to wait on.
                    icon=clock_icon,
                    tip="Put a wait of a working day in front of this step: the wait takes "
                    "what the step waited on, and the step waits on the wait",
                    state=state,
                    run=run,
                )
            )
