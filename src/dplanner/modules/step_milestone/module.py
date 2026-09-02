"""The milestone aspect, in the running application: the Milestone tab, and a Type toggle.

The tab is where a label is written and edited. The Type ▸ Milestone action is the quicker
gesture: toggling on generates the next label from the project's existing ones — or brings
back the one the shelf kept — and toggling off shelves it. Type entries are independent
toggles, never a radio group: what a step *is* emerges from which aspects it carries.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_milestone.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    next_milestone_label,
    project_labels,
    read,
    write,
)
from dplanner.modules.step_milestone.section import MilestoneSection
from dplanner.theme.icons import tag_icon


@dataclass(frozen=True)
class StepMilestoneDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry


class StepMilestoneModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepMilestoneDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=50,
                factory=lambda: MilestoneSection(deps.library, deps.undo),
                # The tab follows the aspect: toggling on generates a label and the tab
                # appears with it, so there is always somewhere to edit one that exists.
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and bool(read(deps.library.step(step_id)))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="milestone.toggle",
                label="Milestone",
                order=10,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=lambda step: bool(read(step)),
                # A fresh milestone generates its label from the ones already there — the
                # same function `dplanner milestone set` uses, one function, two ways in.
                fresh=lambda step, project: write(
                    next_milestone_label(project_labels(project, skip=step.id))
                ),
                icon=tag_icon,
                tip="Mark this step as a milestone point; the label is generated",
            )
        )
