"""What a person can do to a stack, as action specs — the canvas's half of ``stack …``.

Every verb here pushes the very command its ``dplanner stack`` verb applies, built by
``stack_edits.py``: New Stack, Make Stack, Add Step Below, Take Out and Dissolve. A step
born by one — New Stack's first, a stack's "+" — goes through ``StepVerbs.born``, so it is
placed, picked and opened in Step Details exactly as New's is. A card restacked on the
canvas lands here too (:meth:`StackVerbs.drop_into`, :meth:`StackVerbs.drop_out`): the
gesture says where it went, and which of move, add and take out that is, is read here.

**A greyed state never walks the project per announce** (CLAUDE.md). A stack's order, whether
it is still one line, and whether a pick is one line, all take a walk over the project's
links; a state runs on every click and every keystroke. So each state first asks what the
picked steps say alone — how many, which project, which stack — and past that reads a
:class:`_Reading` of the project, built the first time it is asked for and forgotten when the
graph or the canvas's data changes. Typing never rebuilds it; a drag or a link rebuilds it
once. The gesture itself always builds its command fresh, and a builder that refuses says so
on the status line. ``ARCHITECTURE.md``'s *A stack's frame is the stack's handle* has why a
reading built on first read, rather than a settle after a pause.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from dplanner.domain.commands import Command
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.undo import UndoService
from dplanner.modules.project_editor.placement import free_spot, positions
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.positions import NODE_H, NODE_W, node_size, read_stack
from dplanner.modules.project_editor.sorts import H_GAP
from dplanner.modules.project_editor.stack_edits import (
    add_command,
    dissolve_command,
    join_refusal,
    line_refusal,
    make_command,
    make_refusal,
    move_command,
    new_stack_command,
    take_out_command,
)
from dplanner.modules.project_editor.stacks import FRAME_PAD, Stack, frame, read_stacks, stack_of
from dplanner.modules.project_editor.verbs import NEW_STEP_TITLE
from dplanner.theme.icons import make_stack_icon, new_stack_icon

type Seat = tuple[float, float]


@dataclass
class _Reading:
    """What a project's stacks are, as last read: why each one is no longer one line (None
    while it is), and — filled as picks ask — why a pick would not make one."""

    line: dict[str, str | None]
    make: dict[tuple[StepId, ...], str | None] = field(default_factory=dict)


class StackVerbs:
    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        current_project: Callable[[], NodeId | None],
        new_position: Callable[[], Seat | None],
        born: Callable[[Step, Command], None],
        status: Callable[[str], None],
    ) -> None:
        self.library = library
        self.undo = undo
        self.current_project = current_project
        # Where a new stack's first card goes: the canvas's last click, or None.
        self.new_position = new_position
        # Push the command that makes a step, place it, and open its details — StepVerbs'.
        self.born = born
        self.status = status
        self._readings: dict[NodeId, _Reading] = {}
        # What changes a stack's order or line — a link, a step coming or going, the
        # canvas's own data (membership, a seat) — forgets every reading. A title does not:
        # a refusal worded before a rename keeps the old name until the graph next moves.
        library.structure_changed.connect(lambda *_args: self._readings.clear())
        library.edges_changed.connect(lambda *_args: self._readings.clear())
        library.module_data_changed.connect(self._on_module_data)

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="stacks.new",
                label="New Stac&k",
                menu="Graph",
                group="new",
                order=20,
                icon=new_stack_icon,
                tip="Add a stack of one step where the canvas was clicked and open its details",
                state=self._in_a_project,
                run=self._new,
            ),
            ActionSpec(
                id="stacks.make",
                label="&Make Stack",
                menu="Step",
                group="stack",
                submenu="Stack",
                order=10,
                icon=make_stack_icon,
                tip="Stack a line of linked steps where it stands",
                state=self._can_make,
                run=self._make,
            ),
            ActionSpec(
                id="stacks.add_below",
                label="&Add Step Below",
                menu="Step",
                group="stacked",
                submenu="Stack",
                order=10,
                tip="Add a step to the stack under the picked one and open its details",
                state=self._can_add_below,
                run=self._add_below,
            ),
            ActionSpec(
                id="stacks.take_out",
                label="&Take Out of Stack",
                menu="Step",
                group="stacked",
                submenu="Stack",
                order=20,
                tip="Take the picked step out of its stack, with no links, and set it beside",
                state=self._can_take_out,
                run=self._take_out,
            ),
            ActionSpec(
                id="stacks.dissolve",
                label="&Dissolve Stack",
                menu="Step",
                group="stacked",
                submenu="Stack",
                order=30,
                tip="Lay the stack's steps out in a row again; the links stay as they are",
                state=self._can_dissolve,
                run=self._dissolve,
            ),
        ]

    # -- what the picked steps say ------------------------------------------------------------

    def _picked_stack(self, context: Context) -> tuple[list[StepId], str] | None:
        """The picked steps and the id of the one stack they all stand in, or None."""
        chosen = chosen_steps(context, self.library)
        ids = {read_stack(self.library.step(step_id)) for step_id in chosen}
        if not chosen or len(ids) != 1 or "" in ids:
            return None
        return chosen, ids.pop()

    def _reading(self, step_id: StepId) -> _Reading:
        project = self.library.project_of(step_id)
        reading = self._readings.get(project.id)
        if reading is None:
            reading = self._readings[project.id] = _Reading(
                line={
                    stack.id: line_refusal(self.library, stack)
                    for stack in read_stacks(project.steps)
                }
            )
        return reading

    def _on_module_data(self, _node_id: NodeId, module_id: str, *_rest: object) -> None:
        if module_id == POSITION_KEY:
            self._readings.clear()

    # -- state ---------------------------------------------------------------------------------

    def _in_a_project(self, _context: Context) -> ActionState:
        return ENABLED if self.current_project() is not None else DISABLED

    def _can_make(self, context: Context) -> ActionState:
        chosen = chosen_steps(context, self.library)
        if not chosen:
            return DISABLED
        reading = self._reading(chosen[0])
        key = tuple(chosen)
        if key not in reading.make:
            reading.make[key] = make_refusal(self.library, chosen)
        refusal = reading.make[key]
        return (
            ENABLED
            if refusal is None
            else ActionState(enabled=False, label=f"Make Stack — {refusal}")
        )

    def _can_add_below(self, context: Context) -> ActionState:
        return self._edit_state(context, "Add Step Below", one=False)

    def _can_take_out(self, context: Context) -> ActionState:
        return self._edit_state(context, "Take Out of Stack", one=True)

    def _edit_state(self, context: Context, verb: str, *, one: bool) -> ActionState:
        """Enabled while the pick lies in one stack that is still one line — ``one`` asks for
        exactly one of its steps."""
        picked = self._picked_stack(context)
        if picked is None or (one and len(picked[0]) != 1):
            return DISABLED
        refusal = self._reading(picked[0][0]).line.get(picked[1])
        return (
            ENABLED if refusal is None else ActionState(enabled=False, label=f"{verb} — {refusal}")
        )

    def _can_dissolve(self, context: Context) -> ActionState:
        return ENABLED if self._picked_stack(context) is not None else DISABLED

    # -- run -----------------------------------------------------------------------------------

    def _new(self, _context: Context) -> None:
        project_id = self.current_project()
        if project_id is None:
            return  # The state gate already prevents this; stay honest.
        seat = self.new_position() or self._free_seat(self.library.project(project_id))
        step = Step(title=NEW_STEP_TITLE)
        self.born(step, new_stack_command(project_id, step, seat))

    def _free_seat(self, project: Project) -> Seat:
        """A first card's seat whose whole frame lands where nothing is drawn."""
        x, y = free_spot(self.library, project, (NODE_W + 2 * FRAME_PAD, NODE_H + 2 * FRAME_PAD))
        return x + FRAME_PAD, y + FRAME_PAD

    def _make(self, context: Context) -> None:
        chosen = chosen_steps(context, self.library)
        self._push(lambda: make_command(self.library, chosen), "Cannot make a stack")

    def _add_below(self, context: Context) -> None:
        picked = self._picked_stack(context)
        if picked is None:
            return
        chosen, _stack_id = picked
        stack = self._stack(chosen[0])
        slot = max(stack.members.index(step_id) for step_id in chosen) + 1
        step = Step(title=NEW_STEP_TITLE)
        try:
            command = add_command(self.library, step, stack, slot)
        except ValueError as refusal:
            self.status(f"Cannot add a step to the stack — {refusal}")
            return
        self.born(step, command)

    def _take_out(self, context: Context) -> None:
        picked = self._picked_stack(context)
        if picked is None or len(picked[0]) != 1:
            return
        member = picked[0][0]
        stack = self._stack(member)
        seat = self._beside(stack, member)
        self._push(
            lambda: take_out_command(self.library, stack, member, seat), "Cannot take it out"
        )

    def _beside(self, stack: Stack, member: StepId) -> Seat:
        """Where a step taken out of a stack lands: right of its frame, at its own row, or
        the first free row below that."""
        project = self.library.project_of(member)
        seats = positions(self.library, project)
        size_of = {step.id: node_size(step) for step in project.steps}
        left, _top, width, _height = frame(stack, seats[stack.head], size_of.__getitem__)
        near = (left + width + H_GAP, seats[member][1])
        return free_spot(self.library, project, size_of[member], near=near)

    def _dissolve(self, context: Context) -> None:
        picked = self._picked_stack(context)
        if picked is not None:
            self.undo.push(dissolve_command(self.library, self._stack(picked[0][0])))

    # -- a card restacked on the canvas -------------------------------------------------------

    def refusal(self, stack: Stack, joining: StepId | None) -> str | None:
        """Why a gesture may not reorder ``stack`` — or bring ``joining`` into it — or None:
        the builders' own refusals, asked fresh, since a gesture asks once per stack rather
        than on every announce."""
        refusal = line_refusal(self.library, stack)
        if refusal is None and joining is not None:
            refusal = join_refusal(self.library, self.library.step(joining), stack)
        return refusal

    def drop_into(self, step_id: StepId, stack_id: str, slot: int) -> bool:
        """A card let go in a stack at a slot: a member moves there, and any other step
        joins, disconnected. False when nothing was pushed, and the status line says why."""
        steps = self.library.project_of(step_id).steps
        stack = next((one for one in read_stacks(steps) if one.id == stack_id), None)
        if stack is None:
            self.status("Cannot put it in that stack — the stack is gone")
            return False
        if step_id in stack.members:
            return self._push(
                lambda: move_command(self.library, stack, step_id, slot), "Cannot move it there"
            )
        step = self.library.step(step_id)
        return self._push(
            lambda: add_command(self.library, step, stack, slot), "Cannot add it to the stack"
        )

    def drop_out(self, step_id: StepId, seat: Seat) -> bool:
        """A member let go outside its stack's frame: taken out, with no links, at ``seat``."""
        stack = stack_of(self.library.project_of(step_id).steps, step_id)
        if stack is None:
            self.status("Cannot take it out — it is no longer in a stack")
            return False
        return self._push(
            lambda: take_out_command(self.library, stack, step_id, seat), "Cannot take it out"
        )

    def _stack(self, member: StepId) -> Stack:
        """The member's stack as the model has it now — the gesture never reads a reading."""
        found = stack_of(self.library.project_of(member).steps, member)
        assert found is not None  # The state gate read the member's stack key.
        return found

    def _push(self, build: Callable[[], Command], refused: str) -> bool:
        """Push what ``build`` makes, or say why the builder refused — False then."""
        try:
            command = build()
        except ValueError as refusal:
            self.status(f"{refused} — {refusal}")
            return False
        self.undo.push(command)
        return True
