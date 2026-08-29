"""The description aspect, in the running application: one registration, the Description
block on the step panel's Details tab.

The editor itself is :class:`~dplanner.framework.prose_section.ProseSection` — the framework
owns the binding mechanics, so all this module supplies is which document to edit.
"""

from dataclasses import dataclass
from typing import Any

from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library
from dplanner.domain.store import FilesFor
from dplanner.framework.asset_gallery import AreaFor
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService
from dplanner.modules.step_description.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_description.section import (
    DescriptionSection,
    SeparateInstructionLink,
)

PLACEHOLDER = (
    "What this step is — and, on an agent step, what the agent is briefed with."
    " Markdown; images go in with `dplanner describe attach`."
)


@dataclass(frozen=True)
class StepDescriptionDeps:
    library: Library
    undo: UndoService[Library]
    # The step panel's Details tab — the description is its main block, not a tab.
    details: InspectorSectionRegistry
    # The store's file areas — how the tab shows the images `describe attach` wrote.
    # None is a build without file storage.
    files: FilesFor | None = None
    # The agent aspect through this module's own vocabulary, wired by the composition
    # root — the "Separate agent instruction" checkbox. None is a build without agents.
    agent_link: SeparateInstructionLink | None = None


class StepDescriptionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepDescriptionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def field_for(step_id: str) -> TextField[Any] | None:
            if not deps.library.has(step_id):
                return None
            return ModuleTextField(deps.library, step_id, MODULE_ID)

        def area_for_target(step_id: str) -> AreaFor | None:
            files = deps.files
            if files is None or not deps.library.has(step_id):
                return None
            return lambda: files(step_id, MODULE_ID)

        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=20,
                stretch=1,  # The prose is what the leftover height is for.
                factory=lambda: DescriptionSection(
                    field_for,
                    deps.undo,
                    PLACEHOLDER,
                    area_for_target,
                    agent_link=deps.agent_link,
                    library=deps.library,
                ),
            )
        )
