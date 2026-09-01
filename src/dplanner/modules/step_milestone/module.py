"""The milestone aspect, in the running application: the Milestone tab, and a Type toggle.

The tab is where a label is written and edited. The Type ▸ Milestone action is the quicker
gesture: toggling on generates the next label from the project's existing ones, toggling
off asks first — the label is not kept. Type entries are independent toggles, never a
radio group: what a step *is* emerges from which aspects it carries.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
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


@dataclass(frozen=True)
class StepMilestoneDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    parent: QWidget  # confirm()'s parent, as the delete verb's is.


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
            ActionSpec(
                id="milestone.toggle",
                label="Milestone",
                menu="Step",
                group="classify",
                submenu="Type",
                order=10,
                tip="Mark this step as a milestone point; the label is generated",
                state=self._current,
                run=self._toggle,
            )
        )

    def _current(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=bool(read(step)))

    def _toggle(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        label = read(step)
        if not label:
            project = self._deps.library.project_of(step.id)
            new = next_milestone_label(project_labels(project, skip=step.id))
            self._deps.undo.push(
                SetModuleDataCommand(step.id, MODULE_ID, write(new), label="Mark as Milestone")
            )
            return
        question = (
            f"Remove milestone label {label!r} from {step.title or 'this step'!r}?"
            " The label is not kept."
        )
        if not confirm(self._deps.parent, "Clear Milestone", question):
            return
        self._deps.undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write(""), label="Clear Milestone")
        )

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
