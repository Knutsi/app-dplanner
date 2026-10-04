"""The start aspect, in the running application: a Type toggle, and nothing else.

What a start *does* is the walks' business, wired in the composition root; this package
only lets a person say which step it is. The card wears no mark of its own — the origin
is already where every arrow leaves from.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.undo import UndoService
from dplanner.planning.start import DATA_FORMAT, MODULE_ID, SPEC, read, write
from dplanner.theme.icons import mark_starts_icon


@dataclass(frozen=True)
class StepStartDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry


class StepStartModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepStartDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            aspect_toggle(
                id="start.toggle",
                label=SPEC.label,
                order=67,  # A kind, after Wait (65): once per project, so it may fold away.
                module_id=MODULE_ID,
                library=self._deps.library,
                undo=self._deps.undo,
                enabled=read,
                fresh=lambda _step, _project: write(True),
                icon=mark_starts_icon,
                tip="The step the plan begins from: no feature or milestone gathers it",
            )
        )
