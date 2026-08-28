"""What a person can do to a step, as action specs.

**Linking is here, and it is here rather than in the canvas on purpose.** A drop on the canvas
runs :data:`steps.link` exactly as the menu does, so the verb is in the command palette too,
its refusals come from one place, and it can be tested by handing it a constructed ``Context``
with no widget in sight. See ``ARCHITECTURE.md`` for the chain this is one link of.

It reads **two selected steps, in the order they were selected: the second waits on the
first.** That is the drag written down — dragging from A's handle onto B means "A, then B" —
so the canvas and the menu cannot come to mean different things.

**Unlink has two ways of being told which link, and one behaviour.** Two selected steps means
the link between them; selected *edges* mean those edges. Both end in the same command, so
picking an arrow on the canvas and picking its two ends are the same verb rather than two that
have to be kept agreeing. The same reasoning makes Delete act on the whole selection.

**A verb that can act on nothing is disabled, not hidden.** These render as toolbar buttons
now, and a row that reflows as the selection changes is unreadable. ``build_menu`` filters on
*enabled*, so the right-click menu is unchanged and the menu bar greys the entry instead — which
is the better answer there too, since a verb you cannot see is one you cannot learn.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
)
from dplanner.domain.model import NodeId, Product, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.project_editor.selection import EDGE_KIND, EdgeRef, parse_edge_id


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
                tip="Remove the picked links, or the link between the two selected steps",
                state=self._can_unlink,
                run=self._unlink,
            ),
            ActionSpec(
                id="steps.delete",
                label="&Delete Step",
                menu="Step",
                group="edit",
                order=30,
                tip="Remove these steps. Links naming them are left alone, so undo stays exact",
                state=self._can_delete,
                run=self._delete,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _in_a_project(self, _context: Context) -> ActionState:
        return ENABLED if self.current_project() is not None else DISABLED

    def _on_a_step(self, context: Context) -> ActionState:
        step_id = context.focus_entity("step")
        if step_id is None:
            return DISABLED
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
            return DISABLED
        if self._existing_link(context) is not None:
            # The documented exception to "disabled, never hidden": Link and Unlink are one
            # slot, and a greyed "Already linked" beside an enabled Remove Link would say the
            # same fact twice. The label travels anyway, for the canvas reporting a drop onto
            # an already-linked node.
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

    def _picked_edges(self, context: Context) -> list[EdgeRef]:
        """The selected edges that the model still agrees exist."""
        found = [parse_edge_id(entity) for entity in context.selected_entities(EDGE_KIND)]
        return [
            ref
            for ref in found
            if ref is not None
            and self.product.has(ref.waiter)
            and ref.source in self.product.step(ref.waiter).edges.get(ref.kind, [])
        ]

    def _can_unlink(self, context: Context) -> ActionState:
        picked = self._picked_edges(context)
        if picked:
            if len(picked) == 1:
                return ActionState(label="Remove &Link")
            return ActionState(label=f"Remove {len(picked)} &Links")
        return ENABLED if self._existing_link(context) is not None else DISABLED

    def _unlink(self, context: Context) -> None:
        picked = self._picked_edges(context)
        if picked:
            self.undo.push(self._removal_of(picked))
            return
        found = self._existing_link(context)
        pair = self._pair(context)
        if found is None or pair is None:
            return
        waiter, kind = found
        other = pair[0] if pair[1] == waiter else pair[1]
        self.undo.push(self._removal_of([EdgeRef(waiter=waiter, kind=kind, source=other)]))

    def _removal_of(self, refs: list[EdgeRef]) -> Command:
        """One command per ``(waiter, kind)``, because ``SetEdgesCommand`` replaces the list.

        Two commands for the same pair would each be built from the state before either ran,
        and the second would put back what the first removed.
        """
        by_list: dict[tuple[StepId, str], set[StepId]] = {}
        for ref in refs:
            by_list.setdefault((ref.waiter, ref.kind), set()).add(ref.source)
        commands: list[Command] = [
            SetEdgesCommand(
                waiter,
                kind,
                [t for t in self.product.step(waiter).edges.get(kind, []) if t not in gone],
            )
            for (waiter, kind), gone in sorted(by_list.items())
        ]
        if len(commands) == 1:
            return commands[0]
        return CompositeCommand(f"Remove {len(refs)} Links", commands)

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

    def _doomed(self, context: Context) -> list[StepId]:
        """Every selected step, or the one the activity is about — one prompt covers them."""
        chosen = [s for s in context.selected_entities("step") if self.product.has(s)]
        if chosen:
            return chosen
        step_id = context.focus_entity("step")
        return [step_id] if step_id is not None and self.product.has(step_id) else []

    def _can_delete(self, context: Context) -> ActionState:
        doomed = self._doomed(context)
        if not doomed:
            return DISABLED
        if len(doomed) == 1:
            return ENABLED
        return ActionState(label=f"&Delete {len(doomed)} Steps")

    def _delete(self, context: Context) -> None:
        doomed = self._doomed(context)
        if not doomed:
            return
        if len(doomed) == 1:
            title = self.product.step(doomed[0]).title or "this step"
            question = f"Delete {title!r}?"
        else:
            question = f"Delete {len(doomed)} steps?"
        if not confirm(self.parent, "Delete Step", question):
            return
        removals: list[Command] = [RemoveNodeCommand(step_id) for step_id in doomed]
        if len(removals) == 1:
            self.undo.push(removals[0])
        else:
            self.undo.push(CompositeCommand(f"Delete {len(removals)} Steps", removals))
