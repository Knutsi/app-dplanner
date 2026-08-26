"""What a person can do to a step, as action specs.

**Linking is here, and it is here rather than in the canvas on purpose.** A drop on the canvas
runs :data:`steps.link` exactly as the menu does, so the verb is in the command palette too,
its refusals come from one place, and it can be tested by handing it a constructed ``Context``
with no widget in sight. See ``ARCHITECTURE.md`` for the chain this is one link of.

It reads **two selected steps, in the order they were selected: the second waits on the
first.** That is the drag written down — dragging from A's handle onto B means "A, then B" —
so the canvas and the menu cannot come to mean different things.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
)
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
                id="steps.link",
                label="&Link Steps",
                menu="Step",
                group="link",
                order=10,
                tip="The second selected step waits on the first",
                state=self._can_link,
                run=self._link,
            ),
            ActionSpec(
                id="steps.unlink",
                label="&Unlink Steps",
                menu="Step",
                group="link",
                order=20,
                tip="Remove the link between the two selected steps",
                state=self._can_unlink,
                run=self._unlink,
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

    # -- linking -------------------------------------------------------------------------------

    def _pair(self, context: Context) -> tuple[StepId, StepId] | None:
        """The two selected steps as ``(waited on, waiting)``, or None if that is not what
        is selected."""
        chosen = context.selected_entities("step")
        if len(chosen) != 2:
            return None
        source, waiter = chosen
        if not (self.product.has(source) and self.product.has(waiter)):
            return None
        return source, waiter

    def _existing_link(self, context: Context) -> tuple[StepId, str] | None:
        """``(waiter, kind)`` for a link between the pair, whichever way round it runs."""
        pair = self._pair(context)
        if pair is None:
            return None
        source, waiter = pair
        for waits, other in ((waiter, source), (source, waiter)):
            for kind, targets in self.product.step(waits).edges.items():
                if other in targets:
                    return waits, kind
        return None

    def _can_link(self, context: Context) -> ActionState:
        pair = self._pair(context)
        if pair is None:
            return HIDDEN
        if self._existing_link(context) is not None:
            # Out of the menu, because Unlink is what belongs there instead — but the reason
            # travels anyway, for the canvas reporting a drop onto an already-linked node.
            return ActionState(visible=False, enabled=False, label="Already linked")
        source, waiter = pair
        refusal = self.product.link_refusal(waiter, "requires", source)
        if refusal is None:
            return ENABLED
        # The label carries the reason, so a greyed entry says why rather than just being
        # grey — and the canvas reuses it for the status bar after a refused drop.
        return ActionState(enabled=False, label=f"Cannot Link — {refusal}")

    def _link(self, context: Context) -> None:
        pair = self._pair(context)
        if pair is None:
            return  # The state gate already prevents this; stay honest.
        source, waiter = pair
        waiting = self.product.step(waiter).edges.get("requires", [])
        self.undo.push(SetEdgesCommand(waiter, "requires", [*waiting, source]))

    def _can_unlink(self, context: Context) -> ActionState:
        return HIDDEN if self._existing_link(context) is None else ENABLED

    def _unlink(self, context: Context) -> None:
        found = self._existing_link(context)
        pair = self._pair(context)
        if found is None or pair is None:
            return
        waiter, kind = found
        other = pair[0] if pair[1] == waiter else pair[1]
        remaining = [t for t in self.product.step(waiter).edges.get(kind, []) if t != other]
        self.undo.push(SetEdgesCommand(waiter, kind, remaining))

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
