"""What a person can do to a step, as action specs.

Linking is not here. It needs two entities, and nothing publishes a two-entity context — the
canvas expresses it far better as a drag, and the CLI as ``dplanner step link``. A menu entry
that had to open a picker to name its second operand would be worse than both.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import NodeId, Product, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    HIDDEN,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm


@dataclass(frozen=True)
class StepVerbs:
    product: Product
    undo: UndoService[Product]
    parent: QWidget
    # Which project a new step goes into: the one the current tab is showing.
    current_project: Callable[[], NodeId | None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="steps.new",
                label="&New Step…",
                menu="Step",
                group="edit",
                order=10,
                tip="Add a step to the project in this tab",
                state=self._in_a_project,
                run=self._new,
            ),
            ActionSpec(
                id="steps.rename",
                label="&Rename Step…",
                menu="Step",
                group="edit",
                order=20,
                tip="Change what this step is called",
                state=self._on_a_step,
                run=self._rename,
            ),
            ActionSpec(
                id="steps.delete",
                label="&Delete Step",
                menu="Step",
                group="edit",
                order=30,
                tip="Remove this step. Links naming it are left alone, so undo stays exact",
                state=self._on_a_step,
                run=self._delete,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _in_a_project(self, _context: Context) -> ActionState:
        return ENABLED if self.current_project() is not None else HIDDEN

    def _on_a_step(self, context: Context) -> ActionState:
        step_id = context.focus_entity("step")
        if step_id is None:
            return HIDDEN
        return ENABLED if self.product.has(step_id) else DISABLED

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self.product.has(step_id):
            return None
        return self.product.step(step_id)

    # -- run -----------------------------------------------------------------------------------

    def _new(self, _context: Context) -> None:
        project_id = self.current_project()
        if project_id is None:
            return  # The state gate already prevents this; stay honest.
        title, accepted = QInputDialog.getText(self.parent, "New Step", "Step name:")
        if accepted and title.strip():
            self.undo.push(AddNodeCommand(project_id, Step(title=title.strip())))

    def _rename(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        title, accepted = QInputDialog.getText(
            self.parent, "Rename Step", "Step name:", text=step.title
        )
        if accepted and title.strip():
            self.undo.push(SetFieldCommand(step.id, "title", title.strip()))

    def _delete(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        if confirm(self.parent, "Delete Step", f"Delete {step.title!r}?"):
            self.undo.push(RemoveNodeCommand(step.id))

    def delete_many(self, step_ids: list[StepId]) -> None:
        """The canvas's Delete key. One prompt for the whole selection, one undo step."""
        wanted = [s for s in step_ids if self.product.has(s)]
        if not wanted:
            return
        titles = ", ".join(self.product.step(s).title or "untitled" for s in wanted)
        question = f"Delete {titles}?" if len(wanted) == 1 else f"Delete {len(wanted)} steps?"
        if not confirm(self.parent, "Delete Step", question):
            return
        from dplanner.domain.commands import CompositeCommand

        removals = [RemoveNodeCommand(step_id) for step_id in wanted]
        if len(removals) == 1:
            self.undo.push(removals[0])
        else:
            self.undo.push(CompositeCommand(f"Delete {len(removals)} Steps", list(removals)))
