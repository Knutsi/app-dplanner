"""The handoff aspect, in the running application: the Handoff tab and its Type toggle."""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_handoff.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    write_state,
)
from dplanner.modules.step_handoff.section import HandoffSection
from dplanner.theme.icons import handoff_icon


@dataclass(frozen=True)
class StepHandoffDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    # Where a step's handoff files live — the store's `files`, handed in so this module
    # never names a store.
    files: FilesFor


class StepHandoffModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepHandoffDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=60,
                factory=lambda: HandoffSection(deps.library, deps.undo, deps.files),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        # Files in the module's area are left where they are by a toggle: they were never
        # undoable, and the shelf keeps the note that links them.
        deps.actions.register(
            aspect_toggle(
                id="handoff.toggle",
                label=SPEC.label,
                order=90,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: write_state(True),
                icon=handoff_icon,
                tip="Pass a note and files forward to whoever picks up the work after this",
            )
        )
