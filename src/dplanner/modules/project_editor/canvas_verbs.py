"""Verbs that steer the canvas rather than change the plan.

The step verbs next door push commands: they alter the model, they are undoable, and they can
reach nothing but the ``Context``. These are the other family. Moving the selection, entering
connect mode and framing the graph change **what the user is looking at**, so they push no
command, appear on no undo stack, and reach the current canvas through typed callbacks on
their own ``Deps`` — the same seam ``StepVerbs.current_project`` already uses.

Both families are ``ActionSpec``s, and that is the point of putting these here at all. The
canvas keymap binds keys to action ids, so a movement key runs the same object the menu and
the command palette do, and rebinding later is a table rather than a rewrite.

**Where a node is, is a fact about the model.** ``layout.positions()`` already answers it for
every step, stored or automatic, so "the nearest node to the right" is a pure function and
these verbs are testable by constructing a ``Context`` — no canvas, no widget. Only the last
step, telling the canvas what to select, needs the window at all.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.modules.project_editor.layout import positions
from dplanner.modules.project_editor.modes import CONNECT, mode_uri

# Which way each verb looks, as (dx, dy) in scene coordinates — y grows downwards.
DIRECTIONS: dict[str, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
}

# How much a step sideways counts against a candidate compared with a step along the way you
# asked to go. Anything above 1 prefers "roughly in that direction" over "nearest overall",
# which is what makes repeated presses walk a row rather than wander.
OFF_AXIS_COST = 2.0


@dataclass(frozen=True)
class CanvasVerbs:
    product: Product
    # Which project the current tab is showing, as for the step verbs.
    current_project: Callable[[], NodeId | None]
    # The window capabilities these steer. Each is a no-op when no canvas is current.
    select_step: Callable[[StepId], None]
    select_steps: Callable[[list[StepId]], None]
    set_connect_mode: Callable[[bool], None]
    frame: Callable[[], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="steps.connect",
                # Order 5: before Link Steps, because it is how you get to one.
                label="&Connect Steps",
                menu="Step",
                group="link",
                order=5,
                tip="Pick a step, then the step that waits on it. Esc leaves",
                state=self._can_connect,
                run=self._connect,
            ),
            *[
                ActionSpec(
                    id=f"steps.go_{name}",
                    label=name.title(),
                    menu="Step",
                    group="navigate",
                    submenu="Go",
                    order=10 * (index + 1),
                    tip=f"Select the nearest step to the {name}",
                    state=self._can_go(name),
                    run=self._go(name),
                )
                for index, name in enumerate(DIRECTIONS)
            ],
            ActionSpec(
                id="steps.select_all",
                label="Select &All Steps",
                menu="Step",
                group="navigate",
                # After the Go verbs: they walk the selection, this replaces it.
                order=50,
                tip="Select every step in this project",
                state=self._has_steps,
                run=self._select_all,
            ),
            ActionSpec(
                id="canvas.frame",
                label="&Frame Graph",
                menu="View",
                group="canvas",
                tip="Zoom the canvas to the whole graph",
                state=self._on_a_canvas,
                run=lambda _context: self.frame(),
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _on_a_canvas(self, _context: Context) -> ActionState:
        return ENABLED if self.current_project() is not None else DISABLED

    def _can_connect(self, context: Context) -> ActionState:
        """Checked while the mode is on — which is why the mode is in the context at all.

        The canvas publishes its mode as an edge on the activity node, so this stays a pure
        function of the context and the toolbar's checked button costs nothing.
        """
        if self.current_project() is None:
            return DISABLED
        return ActionState(checked=context.edge("mode") == mode_uri(CONNECT))

    def _has_steps(self, _context: Context) -> ActionState:
        project_id = self.current_project()
        if project_id is None or not self.product.has(project_id):
            return DISABLED
        return ENABLED if self.product.project(project_id).steps else DISABLED

    def _can_go(self, name: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            return ENABLED if self._neighbour(context, name) is not None else DISABLED

        return state

    def _go(self, name: str) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            found = self._neighbour(context, name)
            if found is not None:
                self.select_step(found)

        return run

    # -- where the nodes are -----------------------------------------------------------------

    def _neighbour(self, context: Context, name: str) -> StepId | None:
        """The step to move to, or None when there is nowhere that way."""
        project_id = self.current_project()
        from_id = context.focus_entity("step")
        if project_id is None or not self.product.has(project_id):
            return None
        project = self.product.project(project_id)
        placed = positions(self.product, project)
        if from_id is None or from_id not in placed:
            # Nothing picked yet: the first press lands on the step nearest the origin, so a
            # keyboard-only user can start without touching the mouse.
            return min(placed, key=lambda s: (placed[s][1], placed[s][0])) if placed else None

        dx, dy = DIRECTIONS[name]
        origin = placed[from_id]
        best: tuple[float, StepId] | None = None
        for step_id, (x, y) in placed.items():
            if step_id == from_id:
                continue
            along = (x - origin[0]) * dx + (y - origin[1]) * dy
            across = abs((x - origin[0]) * dy) + abs((y - origin[1]) * dx)
            if along <= 0:
                continue
            score = along + OFF_AXIS_COST * across
            if best is None or (score, step_id) < best:
                best = (score, step_id)
        return None if best is None else best[1]

    # -- run -----------------------------------------------------------------------------------

    def _connect(self, context: Context) -> None:
        self.set_connect_mode(context.edge("mode") != mode_uri(CONNECT))

    def _select_all(self, _context: Context) -> None:
        project_id = self.current_project()
        if project_id is None or not self.product.has(project_id):
            return
        self.select_steps([step.id for step in self.product.project(project_id).steps])
