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
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import focused_step
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.positions import write_position
from dplanner.modules.project_editor.selection import EDGE_KIND, EdgeRef, parse_edge_id
from dplanner.theme.icons import plus_icon

# What a step is called until somebody types over it in the details dialog.
NEW_STEP_TITLE = "New step"


def _nowhere() -> tuple[float, float] | None:
    return None


def _unnoticed(_step_id: StepId) -> None:
    return None


@dataclass(frozen=True)
class StepVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    # Which project a new step goes into: the one the current tab is showing.
    current_project: Callable[[], NodeId | None]
    # Where a new node goes — the top-left the canvas's last click asks for, or None when
    # the gesture came from somewhere with no canvas under it (the menu bar over a table).
    # None falls back to the ambient layout, which is what New has always done.
    new_position: Callable[[], tuple[float, float] | None] = _nowhere
    # A step has just been born. The canvas selects it — so the panel beside it is already
    # showing what was made, ready to be described — and steps its remembered point on, so
    # pressing New twice stacks two nodes rather than hiding one under the other. Both
    # belong to whoever placed it; a verb bench in a test has no canvas and needs neither.
    created: Callable[[StepId], None] = _unnoticed

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            # One New, not a submenu of kinds: a step is born plain and configured in the
            # details dialog that opens on it (through the ``created`` seam), where the
            # aspect bar offers every kind and facet at once. ``steps.new`` keeps its id —
            # it is bound to ``N`` in the keymap and wears the toolbar's plus.
            ActionSpec(
                id="steps.new",
                label="&New Step",
                menu="Step",
                group="edit",
                order=10,
                icon=plus_icon,
                tip="Add a step to the project in this tab and open its details",
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
        return ENABLED if self.library.has(step_id) else DISABLED

    # -- linking -------------------------------------------------------------------------------

    def _pair(self, context: Context) -> tuple[StepId, StepId] | None:
        """The two selected steps as ``(waited on, waiting)``, or None if that is not what
        is selected."""
        chosen = context.selected_entities("step")
        if len(chosen) != 2:
            return None
        source, waiter = chosen
        if not (self.library.has(source) and self.library.has(waiter)):
            return None
        return source, waiter

    def _existing_link(self, context: Context) -> tuple[StepId, str] | None:
        """``(waiter, kind)`` for a link between the pair, whichever way round it runs."""
        pair = self._pair(context)
        if pair is None:
            return None
        source, waiter = pair
        for waits, other in ((waiter, source), (source, waiter)):
            for kind, targets in self.library.step(waits).edges.items():
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
        refusal = self.library.link_refusal(waiter, "requires", source)
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
        waiting = self.library.step(waiter).edges.get("requires", [])
        self.undo.push(SetEdgesCommand(waiter, "requires", [*waiting, source]))

    def _picked_edges(self, context: Context) -> list[EdgeRef]:
        """The selected edges that the model still agrees exist."""
        found = [parse_edge_id(entity) for entity in context.selected_entities(EDGE_KIND)]
        return [
            ref
            for ref in found
            if ref is not None
            and self.library.has(ref.waiter)
            and ref.source in self.library.step(ref.waiter).edges.get(ref.kind, [])
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
                [t for t in self.library.step(waiter).edges.get(kind, []) if t not in gone],
            )
            for (waiter, kind), gone in sorted(by_list.items())
        ]
        if len(commands) == 1:
            return commands[0]
        return CompositeCommand(f"Remove {len(refs)} Links", commands)

    # -- run -----------------------------------------------------------------------------------

    def _new(self, _context: Context) -> None:
        """No prompt: the step is born as "New step" and named in the details dialog
        that ``created`` opens on it, where the name field is already selected."""
        project_id = self.current_project()
        if project_id is None:
            return  # The state gate already prevents this; stay honest.
        self.create(project_id, NEW_STEP_TITLE, at=self.new_position())

    def create(
        self,
        project_id: NodeId,
        title: str,
        *,
        at: tuple[float, float] | None = None,
    ) -> Step:
        """Add a step, placed where it was asked for, as **one** undo step.

        The one place a step is born on the canvas: New comes here, and so does the
        double-click on empty space. A gesture is one undo, so the position rides with the
        node rather than arriving as a second entry on the stack.

        A placed step earns a *stored* position, unlike the ambient layout, for the same
        reason a dragged one does: somebody chose where it goes.
        """
        step = Step(title=title)
        commands: list[Command] = [AddNodeCommand(project_id, step)]
        if at is not None:
            commands.append(SetModuleDataCommand(step.id, POSITION_KEY, write_position(*at)))
        self.undo.push(
            commands[0] if len(commands) == 1 else CompositeCommand("New Step", commands)
        )
        self.created(step.id)
        return step

    def _rename(self, context: Context) -> None:
        step = focused_step(context, self.library)
        if step is None:
            return
        title, accepted = QInputDialog.getText(
            self.parent, "Rename Step", "Step name:", text=step.title
        )
        if accepted and title.strip():
            self.undo.push(SetFieldCommand(step.id, "title", title.strip()))

    def _doomed(self, context: Context) -> list[StepId]:
        """Every selected step, or the one the activity is about — one prompt covers them."""
        chosen = [s for s in context.selected_entities("step") if self.library.has(s)]
        if chosen:
            return chosen
        step_id = context.focus_entity("step")
        return [step_id] if step_id is not None and self.library.has(step_id) else []

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
            title = self.library.step(doomed[0]).title or "this step"
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
