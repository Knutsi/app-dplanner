"""The playbook aspect, in the running application: a Details block and a project tab.

A step's block picks its playbook and the overrides a choice of its own may carry; the
project's tab, under *Project ▸ Settings…*, picks what a step that never chose runs. Nothing
here runs a playbook — that is *Run Playbook*'s, once a pass has an engine to drive it.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_playbook.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_playbook.project_section import ProjectPlaybookSection
from dplanner.modules.step_playbook.section import PlaybookSection
from dplanner.planning.kinds import works_nobody
from dplanner.theme.icons import playbook_icon


@dataclass(frozen=True)
class StepPlaybookDeps:
    library: Library
    undo: UndoService[Library]
    details: InspectorSectionRegistry
    project_settings: InspectorSectionRegistry
    harness_ids: tuple[str, ...]  # What a reviewer override may name.


class StepPlaybookModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepPlaybookDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=18,  # After the size and schedule (10 to 15), before the description (20).
                hint="What runs this step when a playbook is started on it: stages that plan, "
                "execute and judge the work. Default is what the project chose for steps like "
                "this one.",
                factory=lambda: PlaybookSection(deps.library, deps.undo, deps.harness_ids),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and not works_nobody(deps.library.step(step_id))
                ),
            )
        )
        deps.project_settings.register(
            InspectorSection(
                id=f"{MODULE_ID}.project",
                label="Playbooks",
                order=25,
                hint="What a step that never chose a playbook runs, and what a landing runs.",
                factory=lambda: ProjectPlaybookSection(deps.library, deps.undo),
                icon=playbook_icon,
            )
        )
