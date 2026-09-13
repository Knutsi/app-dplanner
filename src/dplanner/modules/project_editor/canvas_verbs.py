"""Verbs that steer the canvas rather than change the plan.

The step verbs next door push commands: they alter the model, they are undoable, and they can
reach nothing but the ``Context``. These are the other family. Moving the selection, entering
connect or lasso mode, framing the graph and switching a mark on change **what the user is
looking at**, so they push no command, appear on no undo stack, and reach the current canvas
through typed callbacks on their own ``Deps`` — the same seam ``StepVerbs.current_project``
already uses.

**A mode switch reads the context; the look reads the module.** The canvas publishes its
mode as an edge on the activity node, so a mode button's ``checked`` is a pure function of
the context. The look — the marks, the spotlight, Snap to Grid, the Background submenu — is
a per-user
preference that outlives any tab, so its ``checked`` reads the module's value and the module
asks the context to refresh when it changes — the same shape the theme and panel toggles
use, deliberately not a second thing published per tab.

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

from dplanner.domain.model import SOURCE, WAITER, EdgeEnd, Library, NodeId, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.modules.project_editor.look import BACKGROUNDS, Look
from dplanner.modules.project_editor.marks import MARK_NAMES
from dplanner.modules.project_editor.modes import (
    CONNECT,
    DIVIDE_HORIZONTAL,
    DIVIDE_VERTICAL,
    LASSO,
    REDIRECT_NAMES,
    mode_uri,
)
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.side_panel import SidePanel
from dplanner.modules.project_editor.verbs import picked_edges
from dplanner.theme.icons import (
    connect_icon,
    divide_horizontal_icon,
    divide_vertical_icon,
    frame_icon,
    grid_icon,
    jump_icon,
    lasso_icon,
    mark_ends_icon,
    mark_orphans_icon,
    mark_starts_icon,
    redirect_from_icon,
    redirect_to_icon,
)

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
    # Enter or leave a named canvas mode (modes.CONNECT, modes.LASSO, the divide pair).
    set_mode: Callable[[str, bool], None]
    frame: Callable[[], None]
    # Raise the Jump-to picker over the window; a no-op when no canvas is current.
    jump: Callable[[], None]
    # The user's look — marks, spotlight, background, snapping, the side panel — and a
    # setter for the whole.
    look: Callable[[], Look]
    set_look: Callable[[Look], None]
    # What this build hosts beside the canvas, named by the composition root. None means
    # the capability is absent, and the verb is hidden rather than greyed.
    side_panel: SidePanel | None = None

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
                icon=connect_icon,
                tip="Pick a step, then the step that waits on it. Esc leaves",
                state=self._mode_state(CONNECT),
                run=self._mode_toggle(CONNECT),
            ),
            # The other half of linking, and a submenu of two because an arrow has two ends
            # and which one travels cannot be guessed from a bundle that agrees on neither.
            # Their seat is the link group, after Isolate, so the canvas's right-click — which
            # renders the Step menu — offers them over a picked arrow.
            ActionSpec(
                id="steps.redirect_to",
                label="&To Step",
                menu="Step",
                group="link",
                submenu="Redirect",
                order=40,
                icon=redirect_to_icon,
                tip="Move the picked links so they point to a step you click. Esc leaves",
                state=self._can_redirect(WAITER),
                run=self._mode_toggle(REDIRECT_NAMES[WAITER]),
            ),
            ActionSpec(
                id="steps.redirect_from",
                label="&From Step",
                menu="Step",
                group="link",
                submenu="Redirect",
                order=50,
                icon=redirect_from_icon,
                tip="Move the picked links so they come from a step you click. Esc leaves",
                state=self._can_redirect(SOURCE),
                run=self._mode_toggle(REDIRECT_NAMES[SOURCE]),
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
                id="steps.jump",
                # Order 4: the first of this band. Reveal takes you to the step you have
                # already named; Jump is how you name one.
                label="&Jump to Step…",
                menu="Step",
                group="navigate",
                order=4,
                icon=jump_icon,
                tip="Find a step by name or key and put the canvas on it",
                state=self._on_a_canvas,
                run=lambda _context: self.jump(),
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
                menu="Graph",
                group="look",
                order=10,
                icon=frame_icon,
                tip="Zoom the canvas to the whole graph",
                state=self._on_a_canvas,
                run=lambda _context: self.frame(),
            ),
            ActionSpec(
                id="canvas.divide_vertical",
                label="&Vertical",
                menu="Graph",
                group="arrange",
                submenu="Divide",
                # The 30s: after the Sort and Layout child menus, which claim the 10s and
                # the 20s — a divide rearranges the graph as a sort does, one cut at a time.
                order=30,
                icon=divide_vertical_icon,
                tip="Cut the graph with an upright line and push one side left or right "
                "to make room. Esc leaves",
                state=self._mode_state(DIVIDE_VERTICAL),
                run=self._mode_toggle(DIVIDE_VERTICAL),
            ),
            ActionSpec(
                id="canvas.divide_horizontal",
                label="&Horizontal",
                menu="Graph",
                group="arrange",
                submenu="Divide",
                order=31,
                icon=divide_horizontal_icon,
                tip="Cut the graph with a level line and push one side up or down "
                "to make room. Esc leaves",
                state=self._mode_state(DIVIDE_HORIZONTAL),
                run=self._mode_toggle(DIVIDE_HORIZONTAL),
            ),
            *[
                ActionSpec(
                    id=f"canvas.mark_{name}",
                    label=label,
                    menu="Graph",
                    group="look",
                    submenu="Mark",
                    # After Frame Graph, and before the grid and the ground below it.
                    order=20 + 10 * index,
                    icon=icon,
                    tip=tip,
                    state=self._mark_state(name),
                    run=self._mark_toggle(name),
                )
                for index, (name, label, tip, icon) in enumerate(
                    zip(
                        MARK_NAMES,
                        ("&Starts", "&Ends", "&Orphans"),
                        (
                            "Colour the left socket of every step nothing leads to",
                            "Colour the right socket of every step nothing follows",
                            "Ring every step with no links at all",
                        ),
                        (mark_starts_icon, mark_ends_icon, mark_orphans_icon),
                        strict=True,
                    )
                )
            ],
            ActionSpec(
                id="canvas.side_panel",
                label=f"&{self.side_panel.title}" if self.side_panel else "&Side Panel",
                menu="Graph",
                group="panels",
                order=10,
                icon=self.side_panel.icon if self.side_panel else None,
                tip=(
                    f"Show the {self.side_panel.title} list beside the canvas"
                    if self.side_panel
                    else ""
                ),
                state=self._side_panel_state,
                run=self._side_panel_toggle,
            ),
            ActionSpec(
                id="canvas.spotlight",
                label="&Spotlight Selection",
                menu="Graph",
                group="look",
                # After the Mark submenu, which claims the 20s to the 40s: both are ways of
                # looking at the graph itself. Snap to Grid below is about gestures.
                order=45,
                tip="Fade every step the selection is not linked to. Hold Alt for a moment of it",
                state=self._spotlight_state,
                run=self._spotlight_toggle,
            ),
            ActionSpec(
                id="canvas.snap",
                label="Snap to &Grid",
                menu="Graph",
                group="look",
                # After the Mark submenu: the ground's two entries close the menu.
                order=50,
                icon=grid_icon,
                tip="Land a dragged, resized or newly placed card on the grid",
                state=self._snap_state,
                run=self._snap_toggle,
            ),
            *[
                ActionSpec(
                    id=f"canvas.ground_{name}",
                    label=label,
                    menu="Graph",
                    group="look",
                    submenu="Background",
                    order=60 + 10 * index,
                    tip=tip,
                    state=self._ground_state(name),
                    run=self._ground_pick(name),
                )
                for index, (name, (label, tip)) in enumerate(BACKGROUNDS.items())
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

    def _can_redirect(self, end: EdgeEnd) -> Callable[[Context], ActionState]:
        """Available exactly while links are picked — that is what there is to redirect.

        A greyed entry says so rather than vanishing: the verb is how you learn that
        picking arrows is a thing you can do. It stays enabled while the mode is on
        whatever the selection has become, or there would be no way to leave from the menu.
        """
        name = REDIRECT_NAMES[end]

        def state(context: Context) -> ActionState:
            if self.current_project() is None:
                return DISABLED
            checked = context.edge("mode") == mode_uri(name)
            if checked or picked_edges(self.library, context):
                return ActionState(checked=checked)
            where = "To" if end == WAITER else "From"
            return ActionState(
                enabled=False, checked=False, label=f"&{where} Step — pick links first"
            )

        return state

    def _mark_state(self, name: str) -> Callable[[Context], ActionState]:
        """A preference, so never disabled: switching it off a canvas is harmless and the
        next canvas opened shows it."""

        def state(_context: Context) -> ActionState:
            return ActionState(checked=self.look().marks.is_on(name))

        return state

    def _mark_toggle(self, name: str) -> Callable[[Context], None]:
        def run(_context: Context) -> None:
            self.set_look(self.look().with_mark(name, not self.look().marks.is_on(name)))

        return run

    def _spotlight_state(self, _context: Context) -> ActionState:
        """A preference, like the marks: never disabled, and it reads the module rather than
        the context. The held Alt does not show here — it lends the look, it does not set
        it, and a switch that flickered under a key would be saying something untrue."""
        return ActionState(checked=self.look().spotlight)

    def _spotlight_toggle(self, _context: Context) -> None:
        self.set_look(self.look().with_spotlight(not self.look().spotlight))

    def _side_panel_state(self, _context: Context) -> ActionState:
        """Hidden when this build hosts nothing beside the canvas — the documented use of
        HIDDEN, a capability that is absent rather than a verb that does not apply now."""
        if self.side_panel is None:
            return ActionState(visible=False, enabled=False)
        return ActionState(checked=self.look().side_panel)

    def _side_panel_toggle(self, _context: Context) -> None:
        self.set_look(self.look().with_side_panel(not self.look().side_panel))

    def _snap_state(self, _context: Context) -> ActionState:
        return ActionState(checked=self.look().snap)

    def _snap_toggle(self, _context: Context) -> None:
        self.set_look(self.look().with_snap(not self.look().snap))

    def _ground_state(self, name: str) -> Callable[[Context], ActionState]:
        """One choice of several, so exactly one entry is checked — the theme menu's shape."""

        def state(_context: Context) -> ActionState:
            return ActionState(checked=self.look().background == name)

        return state

    def _ground_pick(self, name: str) -> Callable[[Context], None]:
        def run(_context: Context) -> None:
            self.set_look(self.look().with_background(name))

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
