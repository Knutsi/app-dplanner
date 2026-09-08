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
have to be kept agreeing. The same reasoning makes Delete act on the whole selection — and
:func:`chosen_steps` is that rule written once, so Cut, Copy and Duplicate next door act on
exactly what Delete would.

**Delete asks nothing.** Every removal is one undo step, and a prompt in front of an undoable
verb teaches the wrong lesson — that the gesture is dangerous, when Ctrl+Z is the safety net.
The CLI's ``step remove`` has said so all along; the window now agrees.

**Isolate cuts a selection loose.** Every link into or out of the selected steps goes and
every link among them stays — which edges those are is ``Library.boundary_edges``, and the
command is ``remove_edges_command``, both in the domain so ``dplanner step isolate`` builds
the same object.

**A verb that can act on nothing is disabled, not hidden.** These render as toolbar buttons
now, and a row that reflows as the selection changes is unreadable. ``build_menu`` filters on
*enabled*, so the right-click menu is unchanged and the menu bar greys the entry instead — which
is the better answer there too, since a verb you cannot see is one you cannot learn.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
    remove_edges_command,
    remove_steps_command,
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
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.positions import write_position
from dplanner.modules.project_editor.selection import EDGE_KIND, EdgeRef, parse_edge_id
from dplanner.theme.icons import plus_icon

# What a step is called until somebody types over it in the details dialog.
NEW_STEP_TITLE = "New step"


def _nowhere() -> tuple[float, float] | None:
    return None


def _unnoticed(_step_ids: list[StepId]) -> None:
    return None


def _unnoticed_one(_step_id: StepId) -> None:
    return None


def chosen_steps(library: Library, context: Context) -> list[StepId]:
    """Every selected step that still exists, else the one the activity is about.

    What Delete, Cut, Copy and Duplicate act on — one definition, so the four verbs cannot
    disagree about what "these steps" means.
    """
    chosen = [s for s in context.selected_entities("step") if library.has(s)]
    if chosen:
        return chosen
    step_id = context.focus_entity("step")
    return [step_id] if step_id is not None and library.has(step_id) else []


def picked_edges(library: Library, context: Context) -> list[EdgeRef]:
    """The selected arrows the model still agrees exist — :func:`chosen_steps` for links.

    Unlink acts on them and so does a redirect, which lives next door in ``canvas_verbs``
    because it switches a mode rather than pushing a command; one definition, so no verb
    can come to a different view of what "these links" means.
    """
    found = [parse_edge_id(entity) for entity in context.selected_entities(EDGE_KIND)]
    return [
        ref
        for ref in found
        if ref is not None
        and library.has(ref.waiter)
        and ref.source in library.step(ref.waiter).edges.get(ref.kind, [])
    ]


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
    # Steps have just been placed — born here, or pasted. The canvas selects them — so the
    # panel beside it is already showing what was made, ready to be described — and steps
    # its remembered point on, so pressing New twice stacks two nodes rather than hiding one
    # under the other. Both belong to whoever placed them; a verb bench in a test has no
    # canvas and needs neither.
    placed: Callable[[list[StepId]], None] = _unnoticed
    # One step has just been *born* — by New or a double-click, never a paste. The canvas
    # opens the details dialog on it, so naming it is the gesture's second half; a paste
    # arrives named and gets ``placed`` only.
    created: Callable[[StepId], None] = _unnoticed_one

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
                id="steps.isolate",
                label="&Isolate Steps",
                menu="Step",
                group="link",
                order=30,
                tip="Remove every link into or out of the selected steps; links among them stay",
                state=self._can_isolate,
                run=self._isolate,
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
            # The same verb's second seat, on the Edit menu beside Cut and Copy. Its home
            # stays Step: the canvas, four tables and the toolbar render that menu by name.
            ActionSpec(
                id="steps.delete_edit",
                label="&Delete Step",
                menu="Edit",
                group="clipboard",
                order=50,
                palette=False,
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

    def _can_unlink(self, context: Context) -> ActionState:
        picked = picked_edges(self.library, context)
        if picked:
            if len(picked) == 1:
                return ActionState(label="Remove &Link")
            return ActionState(label=f"Remove {len(picked)} &Links")
        return ENABLED if self._existing_link(context) is not None else DISABLED

    def _unlink(self, context: Context) -> None:
        picked = picked_edges(self.library, context)
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
        label = "Remove Link" if len(refs) == 1 else f"Remove {len(refs)} Links"
        return remove_edges_command(self.library, [ref.as_edge() for ref in refs], label)

    # -- isolating ------------------------------------------------------------------------------

    def _boundary(self, context: Context) -> tuple[list[StepId], list[tuple[StepId, str, StepId]]]:
        chosen = chosen_steps(self.library, context)
        return chosen, self.library.boundary_edges(chosen)

    def _can_isolate(self, context: Context) -> ActionState:
        chosen, boundary = self._boundary(context)
        if not chosen:
            return DISABLED
        if not boundary:
            return ActionState(enabled=False, label="Isolate — already isolated")
        if len(chosen) == 1:
            return ENABLED
        return ActionState(label=f"&Isolate {len(chosen)} Steps")

    def _isolate(self, context: Context) -> None:
        chosen, boundary = self._boundary(context)
        if not boundary:
            return  # The state gate already prevents this; stay honest.
        label = "Isolate Step" if len(chosen) == 1 else f"Isolate {len(chosen)} Steps"
        self.undo.push(remove_edges_command(self.library, boundary, label))

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
        carrying: Callable[[Step], Sequence[Command]] | None = None,
        label: str = "New Step",
    ) -> Step:
        """Add a step, placed where it was asked for, as **one** undo step.

        The one place a step is born on the canvas: New comes here, so does the
        double-click on empty space, and so does a drop. A gesture is one undo, so the
        position rides with the node rather than arriving as a second entry on the stack —
        and so does whatever the step is ``carrying``: the marker a dropped feature arrives
        with, handed in as commands over the not-yet-added step.

        A placed step earns a *stored* position, unlike the ambient layout, for the same
        reason a dragged one does: somebody chose where it goes. A step that arrives
        carrying something arrives *named* — a feature has its title — so it is placed but
        not ``created``: the dialog that names a new step has nothing to ask it.
        """
        step = Step(title=title)
        commands: list[Command] = [AddNodeCommand(project_id, step)]
        if carrying is not None:
            commands += carrying(step)
        if at is not None:
            commands.append(SetModuleDataCommand(step.id, POSITION_KEY, write_position(*at)))
        self.undo.push(commands[0] if len(commands) == 1 else CompositeCommand(label, commands))
        self.placed([step.id])
        if carrying is None:
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

    def _can_delete(self, context: Context) -> ActionState:
        doomed = chosen_steps(self.library, context)
        if not doomed:
            return DISABLED
        if len(doomed) == 1:
            return ENABLED
        return ActionState(label=f"&Delete {len(doomed)} Steps")

    def _delete(self, context: Context) -> None:
        doomed = chosen_steps(self.library, context)
        if doomed:
            self.undo.push(remove_steps_command(self.library, doomed, "Delete"))
