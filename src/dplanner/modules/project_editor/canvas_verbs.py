"""Verbs that steer the canvas rather than change the plan.

The step verbs next door push commands: they alter the model, they are undoable, and they can
reach nothing but the ``Context``. These are the other family. Moving the selection, entering
connect or lasso mode, framing the graph and switching a mark on change **what the user is
looking at**, so they push no command, appear on no undo stack, and reach the current canvas
through typed callbacks on their own ``Deps`` — the same seam ``StepVerbs.current_project``
already uses.

**A mode switch reads the context; a mark reads the module.** The canvas publishes its mode
as an edge on the activity node, so a mode button's ``checked`` is a pure function of the
context. A mark is a per-user preference that outlives any tab, so its ``checked`` reads the
module's value and the module asks the context to refresh when it changes — the same shape
the theme and panel toggles use, deliberately not a second thing published per tab.

Both families are ``ActionSpec``s, and that is the point of putting these here at all. The
canvas keymap binds keys to action ids, so a movement key runs the same object the menu and
the command palette do, and rebinding later is a table rather than a rewrite. Select All is
the one with a menu shortcut instead — it lives on the Edit menu, where every editor expects
Ctrl+A to be, and stays here because it steers the canvas rather than changing the plan.

**Where a node is, is a fact about the model.** ``layout.positions()`` already answers it for
every step, stored or automatic, so "the nearest node to the right" is a pure function and
these verbs are testable by constructing a ``Context`` — no canvas, no widget. Only the last
step, telling the canvas what to select, needs the window at all.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QKeySequence

from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.modules.project_editor.marks import MARK_NAMES, Marks
from dplanner.modules.project_editor.modes import CONNECT, LASSO, mode_uri
from dplanner.modules.project_editor.placement import positions
from dplanner.theme.icons import lasso_icon

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
    library: Library
    # Which project the current tab is showing, as for the step verbs.
    current_project: Callable[[], NodeId | None]
    # The window capabilities these steer. Each is a no-op when no canvas is current.
    select_step: Callable[[StepId], None]
    select_steps: Callable[[list[StepId]], None]
    # Enter or leave a named canvas mode (modes.CONNECT, modes.LASSO).
    set_mode: Callable[[str, bool], None]
    frame: Callable[[], None]
    # The user's marks, and the switch for one of them by name (marks.MARK_NAMES).
    marks: Callable[[], Marks]
    set_mark: Callable[[str, bool], None]

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
                state=self._mode_state(CONNECT),
                run=self._mode_toggle(CONNECT),
            ),
            ActionSpec(
                id="steps.lasso",
                label="Lasso &Select",
                menu="Step",
                group="navigate",
                # After the Go verbs and before Select All: it is the other way to pick many.
                order=40,
                icon=lasso_icon,
                tip="Draw round the steps to select them. Shift adds. Esc leaves",
                state=self._mode_state(LASSO),
                run=self._mode_toggle(LASSO),
            ),
            ActionSpec(
                id="steps.reveal",
                # Order 5: before the Go submenu — it is the "take me there" of this group.
                label="Re&veal in Graph",  # &v: R is Rename's.
                menu="Step",
                group="navigate",
                order=5,
                tip="Show this step on its project's canvas",
                state=self._can_reveal,
                run=self._reveal,
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
                menu="Edit",
                group="selection",
                order=10,
                # A menu shortcut rather than a canvas key: every text widget reclaims
                # Ctrl+A through ShortcutOverride, and the state gate keeps it off a tab
                # with no canvas. keymap.py says why the bare keys stay there.
                shortcut=QKeySequence.StandardKey.SelectAll,
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
            *[
                ActionSpec(
                    id=f"canvas.mark_{name}",
                    label=label,
                    menu="View",
                    group="canvas",
                    submenu="Mark",
                    # After Frame Graph; the Sort and Layout child menus sit at 10.
                    order=60 + 10 * index,
                    tip=tip,
                    state=self._mark_state(name),
                    run=self._mark_toggle(name),
                )
                for index, (name, label, tip) in enumerate(
                    zip(
                        MARK_NAMES,
                        ("&Starts", "&Ends", "&Orphans"),
                        (
                            "Colour the left socket of every step nothing leads to",
                            "Colour the right socket of every step nothing follows",
                            "Ring every step with no links at all",
                        ),
                        strict=True,
                    )
                )
            ],
        ]

    # -- state ---------------------------------------------------------------------------------

    def _on_a_canvas(self, _context: Context) -> ActionState:
        return ENABLED if self.current_project() is not None else DISABLED

    def _mode_state(self, name: str) -> Callable[[Context], ActionState]:
        """Checked while the mode is on — which is why the mode is in the context at all.

        The canvas publishes its mode as an edge on the activity node, so this stays a pure
        function of the context and the toolbar's checked button costs nothing.
        """

        def state(context: Context) -> ActionState:
            if self.current_project() is None:
                return DISABLED
            return ActionState(checked=context.edge("mode") == mode_uri(name))

        return state

    def _mode_toggle(self, name: str) -> Callable[[Context], None]:
        def run(context: Context) -> None:
            self.set_mode(name, context.edge("mode") != mode_uri(name))

        return run

    def _mark_state(self, name: str) -> Callable[[Context], ActionState]:
        """A preference, so never disabled: switching it off a canvas is harmless and the
        next canvas opened shows it."""

        def state(_context: Context) -> ActionState:
            return ActionState(checked=self.marks().is_on(name))

        return state

    def _mark_toggle(self, name: str) -> Callable[[Context], None]:
        def run(_context: Context) -> None:
            self.set_mark(name, not self.marks().is_on(name))

        return run

    def _has_steps(self, _context: Context) -> ActionState:
        project_id = self.current_project()
        if project_id is None or not self.library.has(project_id):
            return DISABLED
        return ENABLED if self.library.project(project_id).steps else DISABLED

    def _can_reveal(self, context: Context) -> ActionState:
        """One selected, resolvable step — deliberately not gated on a current canvas.

        The verb's home is the order table's and the board's context menus, where no canvas
        is current; ``select_step`` opens the step's project tab on its way there.
        """
        step_id = context.selected_entity("step")
        if step_id is None or not self.library.has(step_id):
            return DISABLED
        return ENABLED

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
        if project_id is None or not self.library.has(project_id):
            return None
        project = self.library.project(project_id)
        placed = positions(self.library, project)
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

    def _reveal(self, context: Context) -> None:
        step_id = context.selected_entity("step")
        if step_id is not None and self.library.has(step_id):
            self.select_step(step_id)

    def _select_all(self, _context: Context) -> None:
        project_id = self.current_project()
        if project_id is None or not self.library.has(project_id):
            return
        self.select_steps([step.id for step in self.library.project(project_id).steps])
