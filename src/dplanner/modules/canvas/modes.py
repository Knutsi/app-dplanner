"""Canvas input, as a stack of modes.

A **mode** is an object that handles input and has power over the view. They stack, and
popping one returns to the one below, so a behaviour that is only true for a while — a link
being dragged, space being held — is a whole object with a beginning and an end rather than
a flag somebody has to remember to clear. That is the point: the gesture state this replaced
lived as ``_link_from`` beside ``_press_at`` on the scene, and the first bug it produced was
a handler reading a field a previous line had already emptied.

Three rules keep it small:

- **Returning False costs nothing.** A hook that does not claim the event lets it fall
  through — to the canvas keymap, and then to Qt, which already does rubber-band selection,
  item dragging and hand-scrolling. :class:`IdleMode` is nine lines because of this.
- **A mode reports; it never writes.** It emits the canvas's signals and the activity turns
  those into commands, exactly as before. Nothing here reaches the model or the undo stack.
- **A mode asks the model.** Whether a link is legal is ``Library.link_refusal`` under the
  cursor, reached through :class:`Canvas`. There is no second reachability rule in here.

A mode that drags something the canvas draws — a card by its frame, every card on one side
of a cut, the pick with its stacks whole, one card into, through or out of a stack — is a
:class:`GestureMode`: it holds what it moves
so a sync leaves the geometry alone, Escape puts everything back, and the release reports and
pops. A new one says what it holds, how to restore it, and what the release means, and
inherits the rest.

**A stack is one node to a link.** Wherever a link end lands on a stack — any of its cards,
its frame — it means the stack's first card for an arrowhead and its last for a tail, the
scene's ``link_end``; whether that link is legal is still ``link_refusal``'s alone.

:class:`Canvas` is the whole of a mode's power over the canvas, which is why it is written
out rather than inferred from passing the scene around: a mode can be driven in a test by
anything that satisfies it, and a new mode cannot quietly grow a reach nobody sanctioned.

All of them live in this one file because a mode is only worth reading beside the others —
what each one claims is what the next one therefore never sees. Split it when a single mode
outgrows a screen, not when the file does.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsView

from dplanner.core.signals import Signal
from dplanner.domain.model import SOURCE, WAITER, EdgeEnd, Redirection, StepId
from dplanner.framework.motion.clock import FrameClock
from dplanner.framework.motion.curves import out_cubic, span
from dplanner.modules.canvas.geometry import Axis, contract, direction, shift
from dplanner.modules.canvas.items import HANDLE_GRAB, StackItem, StepNodeItem
from dplanner.modules.canvas.layouts.named import Point
from dplanner.modules.canvas.layouts.positions import MIN_NODE_H, MIN_NODE_W, centred_on
from dplanner.modules.canvas.renderers import RenderHints
from dplanner.modules.canvas.selection import CanvasSelection, EdgeRef
from dplanner.modules.canvas.stacks.stack import FRAME_PAD, Packing, Stack, frame, member_seats

# How the current mode reaches the context, so an action's ``state`` can read it as a pure
# function — which is what makes the Connect toolbar button check itself for free.
MODE_URI_PREFIX = "app://canvas-mode/"

IDLE = "idle"
CONNECT = "connect"
PAN = "pan"
LINK_DRAG = "link-drag"
NODE_RESIZE = "node-resize"
BLOCK_DRAG = "block-drag"
RESTACK = "restack"
LASSO = "lasso"
DIVIDE_VERTICAL = "divide-vertical"
DIVIDE_HORIZONTAL = "divide-horizontal"
CONTRACT_VERTICAL = "contract-vertical"
CONTRACT_HORIZONTAL = "contract-horizontal"
REDIRECT_TO = "redirect-to"
REDIRECT_FROM = "redirect-from"
STRIP_PRESS = "strip-press"

# The redirect modes by the end of the arrow they move. An arrow runs from the step waited
# on to the step that waits, so moving the waiter end aims the picked links *at* a step and
# moving the source end makes them come *from* one.
REDIRECT_NAMES: dict[EdgeEnd, str] = {WAITER: REDIRECT_TO, SOURCE: REDIRECT_FROM}

# The divide and contract modes by the line they cut with: a vertical line parts left from
# right and moves a side along x; a horizontal one parts top from bottom and moves along y.
DIVIDE_NAMES: dict[Qt.Orientation, str] = {
    Qt.Orientation.Vertical: DIVIDE_VERTICAL,
    Qt.Orientation.Horizontal: DIVIDE_HORIZONTAL,
}
CONTRACT_NAMES: dict[Qt.Orientation, str] = {
    Qt.Orientation.Vertical: CONTRACT_VERTICAL,
    Qt.Orientation.Horizontal: CONTRACT_HORIZONTAL,
}


def mode_uri(name: str) -> str:
    return f"{MODE_URI_PREFIX}{name}"


# What each mode wants every node to show, fanned out by the scene when the stack changes.
# Kept beside the mode names so a new mode decides its look in the same breath. Connect
# shows every handle — each is a target; pan, resize, lasso, divide, contract and redirect
# hide them — their presses do not link. Anything unlisted gets the default (idle's
# hover-only handle).
HINTS_BY_MODE = {
    CONNECT: RenderHints(handles="always"),
    PAN: RenderHints(handles="hidden"),
    NODE_RESIZE: RenderHints(handles="hidden"),
    BLOCK_DRAG: RenderHints(handles="hidden"),
    RESTACK: RenderHints(handles="hidden"),
    LASSO: RenderHints(handles="hidden"),
    DIVIDE_VERTICAL: RenderHints(handles="hidden"),
    DIVIDE_HORIZONTAL: RenderHints(handles="hidden"),
    CONTRACT_VERTICAL: RenderHints(handles="hidden"),
    CONTRACT_HORIZONTAL: RenderHints(handles="hidden"),
    REDIRECT_TO: RenderHints(handles="hidden"),
    REDIRECT_FROM: RenderHints(handles="hidden"),
}

# With Space held, an arrow or a vim key moves the view by this share of the viewport in
# that direction — a page — and with Shift by the smaller one — a nudge.
PAN_PAGE = 1 / 3
PAN_NUDGE = 1 / 10
PAN_KEYS: dict[int, tuple[int, int]] = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_H: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_L: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_K: (0, -1),
    Qt.Key.Key_Down: (0, 1),
    Qt.Key.Key_J: (0, 1),
}

# The cursor a card's edge or corner shows, keyed by what ``StepNodeItem.edge_at`` answers.
RESIZE_CURSORS = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "top": Qt.CursorShape.SizeVerCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "top-left": Qt.CursorShape.SizeFDiagCursor,
    "bottom-right": Qt.CursorShape.SizeFDiagCursor,
    "top-right": Qt.CursorShape.SizeBDiagCursor,
    "bottom-left": Qt.CursorShape.SizeBDiagCursor,
}

# How long the cards of a stack take to make way for one dragged through it: long enough to
# be seen moving, short enough never to trail the hand.
MAKE_WAY_S = 0.12

# The cursor over a cut: the splitter's, since that is the gesture — a side of a vertical
# line moves left or right, of a horizontal one up or down.
CUT_CURSORS = {
    Qt.Orientation.Vertical: Qt.CursorShape.SplitHCursor,
    Qt.Orientation.Horizontal: Qt.CursorShape.SplitVCursor,
}


# -- what a mode is handed ---------------------------------------------------------------------


@dataclass(frozen=True)
class CanvasEvent:
    """A mouse event in scene coordinates, with the widget left out on purpose.

    ``view_pos`` is the same point in the viewport's device pixels — what a pan needs,
    since it moves the viewport by the pointer's travel and the scene slides under it.
    """

    scene_pos: QPointF
    view_pos: QPointF = field(default_factory=QPointF)
    button: Qt.MouseButton = Qt.MouseButton.NoButton
    buttons: Qt.MouseButton = Qt.MouseButton.NoButton
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier


@dataclass(frozen=True)
class CanvasKey:
    key: int
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    auto_repeat: bool = False


class Canvas(Protocol):
    """Everything a mode may do to the canvas, and nothing else."""

    # The steps to be waited on, and the one step that waits on all of them.
    link_requested: Signal[tuple[StepId, ...], StepId]
    create_requested: Signal[float, float]
    selection_changed: Signal[CanvasSelection]
    # A card that finished resizing: its new seat and size, since an edge may have moved.
    node_resized: Signal[StepId, float, float, float, float]
    # The cards a divide pushed, at their new seats — one gesture, one emission.
    graph_divided: Signal[list[tuple[StepId, float, float]]]
    # The cards a contract pulled up, the same way.
    graph_contracted: Signal[list[tuple[StepId, float, float]]]
    # The step the picked links are to hang off, and which end of them moves.
    redirect_requested: Signal[StepId, EdgeEnd]
    # Cards a drag put down, at their new seats — Qt's own drag and a block drag alike.
    nodes_moved: Signal[list[tuple[StepId, float, float]]]
    # A stack's "+" was pressed: a step is wanted below this one, the stack's last.
    stack_add_requested: Signal[StepId]
    # A card's playbook strip was clicked: the step's pass is wanted, in Step Details.
    playbook_opened: Signal[StepId]
    # A card restacked — let go in the stack with this id at this slot, or out of its own
    # stack at this seat: where it went; which verb that is, is the model's to say.
    dropped_into_stack: Signal[StepId, str, int]
    dropped_out_of_stack: Signal[StepId, float, float]

    def node_at(self, scene_pos: QPointF) -> StepNodeItem | None: ...

    def node(self, step_id: StepId) -> StepNodeItem | None: ...

    # Every card on the canvas — what a divide parts into two sides.
    def nodes(self) -> list[StepNodeItem]: ...

    # The stacks drawn now, whole — what a cut packs into blocks.
    def stacks(self) -> list[Stack]: ...

    # The stack whose frame or "+" is the topmost thing at a point; the stack whose "+" is.
    def frame_at(self, scene_pos: QPointF) -> Stack | None: ...

    def add_at(self, scene_pos: QPointF) -> Stack | None: ...

    # A stack's frame, which a gesture reordering its column borrows (``StackItem.stand``).
    def frame(self, stack_id: str) -> StackItem | None: ...

    # Why this stack cannot be reordered — or take ``joining`` in — or None: the model's
    # answer, as ``link_refusal`` is for a link.
    def stack_refusal(self, stack: Stack, joining: StepId | None) -> str | None: ...

    # The frame round a point says what Shift does; None quiets every one.
    def hint_at(self, scene_pos: QPointF | None) -> None: ...

    # A card in the hand: its arrows are not drawn until it lands, or None to draw them all.
    def lift_links(self, step_id: StepId | None) -> None: ...

    # What a link end landing on this step means: a stack's first card for an arrowhead,
    # its last for a tail — and the card a link end at a point lands on, frames included.
    def link_end(self, step_id: StepId, end: EdgeEnd) -> StepId: ...

    def link_target_at(self, scene_pos: QPointF, end: EdgeEnd) -> StepNodeItem | None: ...

    def select_step(self, step_id: StepId | None) -> None: ...

    def select_steps(self, step_ids: list[StepId]) -> None: ...

    def selected_step(self) -> StepId | None: ...

    def selection(self) -> CanvasSelection: ...

    def nodes_touching(self, path: QPainterPath) -> list[StepNodeItem]: ...

    def link_refusal(self, waiter: StepId, source: StepId) -> str | None: ...

    # What moving one end of these edges onto a step would do. The model's answer, so the
    # ring under the cursor and the command that follows cannot disagree — the same reason
    # ``link_refusal`` is here rather than a rule of the mode's own.
    def redirection(
        self, edges: Sequence[EdgeRef], anchor: StepId, end: EdgeEnd
    ) -> Redirection: ...

    def aim_preview(self, origin: QPointF, cursor: QPointF, ok: bool) -> None: ...

    def hide_preview(self) -> None: ...

    def set_link_states(self, valid: StepId | None, invalid: StepId | None) -> None: ...

    # The one outline a gesture drawing an area shows: a lasso's path, a divide's band.
    def aim_outline(self, path: QPainterPath) -> None: ...

    def hide_outline(self) -> None: ...

    # A coordinate on the grid while Snap to Grid is on, else itself: what every gesture
    # that produces a position or a size runs its numbers through.
    def snap(self, value: float) -> float: ...

    # A mode owns these steps' geometry until it releases: the scene's sync leaves them
    # where the gesture has them.
    def hold(self, step_ids: set[StepId]) -> None: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class ModeDeps:
    """A mode's services, named the way a module's ``Deps`` are one layer up."""

    canvas: Canvas
    view: QGraphicsView
    status: Callable[[str], None]
    # Run an action id against the current context; False when the state gate refused it.
    # A mode never holds the registry, so it cannot run anything the menus could not.
    run_action: Callable[[str], bool]


# -- the stack ---------------------------------------------------------------------------------


class ModeBase:
    """Declines every event. A mode overrides only the hooks it has an opinion about."""

    name = IDLE

    def __init__(self, deps: ModeDeps) -> None:
        self.deps = deps
        # Set by ModeStack when this mode is pushed; a mode that starts another one — idle
        # starting a link drag — is the normal case, so it needs the stack it lives on.
        self.stack: ModeStack | None = None

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def mouse_press(self, event: CanvasEvent) -> bool:
        return False

    def mouse_move(self, event: CanvasEvent) -> bool:
        return False

    def mouse_release(self, event: CanvasEvent) -> bool:
        return False

    def double_click(self, event: CanvasEvent) -> bool:
        return False

    def key_press(self, key: CanvasKey) -> bool:
        return False

    def key_release(self, key: CanvasKey) -> bool:
        return False


class ModeStack:
    """The current mode, and the ones it will fall back to. The base never pops."""

    def __init__(self, base: ModeBase) -> None:
        self._stack: list[ModeBase] = [base]
        self.changed: Signal[str] = Signal()
        base.stack = self
        base.enter()

    def current(self) -> ModeBase:
        return self._stack[-1]

    def push(self, mode: ModeBase) -> None:
        mode.stack = self
        self._stack.append(mode)
        mode.enter()
        self.changed.emit(mode.name)

    def pop(self) -> bool:
        """Leave the top mode. False when there is nothing above the base to leave."""
        if len(self._stack) == 1:
            return False
        self._stack.pop().exit()
        self.changed.emit(self.current().name)
        return True

    def pop_to_base(self) -> None:
        while self.pop():
            pass

    def dispose(self) -> None:
        while len(self._stack) > 1:
            self._stack.pop().exit()
        self._stack[0].exit()


# -- linking -------------------------------------------------------------------------------------


class _LinkingMode(ModeBase):
    """The half that connect and the handle drag share: a preview, and the model's refusal.

    ``_refusal`` takes both ends as arguments rather than reading one off the gesture. That
    is not style — the release handler this came from cleared its source on its first line
    and then asked about it, so every drop refused itself for a fortnight.

    The sources are plural because Connect adopts a whole selection: every one of them is
    waited on by the one target, and one refusal refuses the lot, as ``steps.link`` does.
    """

    def _refusal(self, sources: tuple[StepId, ...], target: StepId) -> str | None:
        for source in sources:
            if source == target:
                return "a step cannot depend on itself"
            refusal = self.deps.canvas.link_refusal(target, source)
            if refusal is not None:
                return refusal
        return None

    def _aim(self, sources: tuple[StepId, ...], cursor: QPointF) -> None:
        canvas = self.deps.canvas
        target = canvas.link_target_at(cursor, WAITER)
        origin_node = canvas.node(sources[0])
        if origin_node is None:
            return
        origin = origin_node.handle_scene_pos()
        ok = target is not None and self._refusal(sources, target.step_id) is None
        if target is None or target.step_id in sources:
            canvas.set_link_states(None, None)
        else:
            canvas.set_link_states(target.step_id if ok else None, None if ok else target.step_id)
        canvas.aim_preview(origin, cursor, ok)

    def _aim_at_step(self, sources: tuple[StepId, ...], target: StepId) -> None:
        """Aim at a whole node rather than at a point — what keyboard navigation produces."""
        canvas = self.deps.canvas
        target = canvas.link_end(target, WAITER)
        origin_node, target_node = canvas.node(sources[0]), canvas.node(target)
        if origin_node is None or target_node is None:
            return
        ok = self._refusal(sources, target) is None
        canvas.set_link_states(target if ok else None, None if ok else target)
        canvas.aim_preview(
            origin_node.handle_scene_pos(), target_node.sceneBoundingRect().center(), ok
        )

    def _tails(self, step_ids: Sequence[StepId]) -> tuple[StepId, ...]:
        """The steps a link would leave from: a stack's last card for any of its own, each
        once — so a stack picked whole is one source, not every member."""
        return tuple(dict.fromkeys(self.deps.canvas.link_end(s, SOURCE) for s in step_ids))

    def _propose(self, sources: tuple[StepId, ...], target: StepId) -> None:
        """Hand the steps to the activity, which runs ``steps.link`` exactly as the menu does."""
        self.deps.canvas.link_requested.emit(sources, target)

    def _clear(self) -> None:
        self.deps.canvas.hide_preview()
        self.deps.canvas.set_link_states(None, None)


class LinkDragMode(_LinkingMode):
    """Dragging from a node's handle. Lives for exactly one drag and pops itself."""

    name = LINK_DRAG

    def __init__(self, deps: ModeDeps, source: StepId) -> None:
        super().__init__(deps)
        self._sources = (source,)

    def enter(self) -> None:
        node = self.deps.canvas.node(self._sources[0])
        if node is not None:
            self._aim(self._sources, node.handle_scene_pos())

    def exit(self) -> None:
        self._clear()

    def mouse_move(self, event: CanvasEvent) -> bool:
        self._aim(self._sources, event.scene_pos)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        target = self.deps.canvas.link_target_at(event.scene_pos, WAITER)
        if target is not None and target.step_id not in self._sources:
            self._propose(self._sources, target.step_id)
        self._pop()
        return True

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            self._pop()
            return True
        return False

    def _pop(self) -> None:
        if self.stack is not None:
            self.stack.pop()


class ConnectMode(_LinkingMode):
    """Pick the steps others wait on, then the step that waits — with the mouse or the keys.

    It adopts whatever is selected as its sources, so entering the mode with a step in front
    of you means you are already halfway — and entering it with several means the next
    click links every one of them to the step clicked. Movement keys are *not* consumed:
    they fall through to the canvas keymap and move the selection, and this mode re-aims at
    wherever they landed. Enter finishes the link, and one finished link ends the mode.
    """

    name = CONNECT

    def __init__(self, deps: ModeDeps) -> None:
        super().__init__(deps)
        self._sources: tuple[StepId, ...] = ()
        self._unsubscribe: Callable[[], None] | None = None

    def enter(self) -> None:
        self._unsubscribe = self.deps.canvas.selection_changed.connect(self._on_selection)
        self.deps.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._take_sources(self._tails(self.deps.canvas.selection().steps))

    def exit(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.deps.view.viewport().unsetCursor()
        self._clear()

    def mouse_press(self, event: CanvasEvent) -> bool:
        canvas = self.deps.canvas
        source = canvas.link_target_at(event.scene_pos, SOURCE)
        target = canvas.link_target_at(event.scene_pos, WAITER)
        if source is None or target is None:
            self._take_sources(())
        elif not self._sources or source.step_id in self._sources:
            canvas.select_step(source.step_id)
            self._take_sources((source.step_id,))
        else:
            self._finish(target.step_id)
        return True  # Consumed either way: no node dragging and no rubber band in this mode.

    def mouse_move(self, event: CanvasEvent) -> bool:
        if self._sources:
            self._aim(self._sources, event.scene_pos)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A second click is the second step, never a new one.

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            if not self._sources:
                return False  # Nothing pending: the canvas pops the mode instead.
            self._take_sources(())
            return True
        if key.key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            picked = self.deps.canvas.selected_step()
            target = None if picked is None else self.deps.canvas.link_end(picked, WAITER)
            if self._sources and target is not None and target not in self._sources:
                self._finish(target)
            return True
        return False  # Movement keys belong to the keymap; this mode follows what they select.

    def _take_sources(self, step_ids: tuple[StepId, ...]) -> None:
        self._sources = step_ids
        self._clear()
        if not step_ids:
            self.deps.status("Connect: pick the step others wait on. Esc leaves.")
        elif len(step_ids) == 1:
            self.deps.status("Connect: pick the step that waits. Enter links, Esc cancels.")
        else:
            self.deps.status(
                f"Connect: pick the step that waits on these {len(step_ids)}."
                " Enter links, Esc cancels."
            )

    def _on_selection(self, selection: CanvasSelection) -> None:
        if not self._sources or len(selection.steps) != 1:
            return
        target = selection.steps[0]
        if target not in self._sources:
            self._aim_at_step(self._sources, target)

    def _finish(self, target: StepId) -> None:
        assert self._sources
        self._propose(self._sources, target)
        if self.stack is not None:
            self.stack.pop()


class RedirectMode(ModeBase):
    """Pick the step the selected links should hang off, and move that end of every one.

    The other half of linking. Connect makes one arrow between two steps; this takes a
    bundle of arrows already drawn and moves one of their ends somewhere else — which is
    what "these six things now wait on the new step instead" looks like as a gesture,
    rather than as six unlinks and six links.

    Which end travels is the mode's, not something inferred from what was picked: an
    arrow has two ends and a bundle spanning several steps agrees on neither, so guessing
    would be a rule nobody could predict. :data:`REDIRECT_NAMES` names the two.

    The links are taken at entry — every press is consumed, so nothing can change the
    selection underneath — and the step under the cursor wears the same valid/invalid ring
    a link drag paints, because the answer is per step: an arrow that would close a cycle
    cannot go there while the rest of the bundle still can. Like a divide, the mode reports
    and the activity commands, and one redirect ends the mode.
    """

    def __init__(self, deps: ModeDeps, end: EdgeEnd) -> None:
        super().__init__(deps)
        self._end = end
        self.name = REDIRECT_NAMES[end]
        self._edges: tuple[EdgeRef, ...] = ()

    def enter(self) -> None:
        self._edges = self.deps.canvas.selection().edges
        self.deps.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.deps.status(
            f"Redirect: click the step {self._count()} should"
            f" {'point to' if self._end == WAITER else 'come from'}. Esc leaves."
        )

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.set_link_states(None, None)

    def mouse_press(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.link_target_at(event.scene_pos, self._end)
        if node is not None:
            plan = self._plan(node.step_id)
            if plan.moving:
                self.deps.canvas.redirect_requested.emit(node.step_id, self._end)
                if self.stack is not None:
                    self.stack.pop()
            elif plan.refused:
                self.deps.status(f"Cannot redirect there — {plan.refused[0][1]}")
        return True  # Consumed either way: no node dragging and no rubber band in here.

    def mouse_move(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.link_target_at(event.scene_pos, self._end)
        if node is None:
            self.deps.canvas.set_link_states(None, None)
        elif self._plan(node.step_id).moving:
            self.deps.canvas.set_link_states(node.step_id, None)
        else:
            self.deps.canvas.set_link_states(None, node.step_id)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A second click is still a target, never a new step.

    def _plan(self, anchor: StepId) -> Redirection:
        return self.deps.canvas.redirection(self._edges, anchor, self._end)

    def _count(self) -> str:
        return "this link" if len(self._edges) == 1 else f"these {len(self._edges)} links"


class PanMode(ModeBase):
    """Hold space and drag the plane, wherever the press lands — or step it with the keys.

    It claims every press and moves the viewport itself, by the pointer's travel in device
    pixels through the hidden scroll bars. Not Qt's ``ScrollHandDrag``: that hands a press
    to the item under it first, so a press on a card moved the card — the one thing a hand
    holding Space does not mean. The seat of the plane is taken at the press, so the point
    grabbed stays under the pointer however far the drag goes.

    With Space held the arrows and ``hjkl`` page the view a third of the viewport that way,
    a tenth with Shift. They are claimed here, before the canvas keymap sees them, so the
    same keys stop selecting steps for as long as the hand is on the plane.
    """

    name = PAN

    def __init__(self, deps: ModeDeps) -> None:
        super().__init__(deps)
        self._grab: QPointF | None = None
        self._seat = (0, 0)

    def enter(self) -> None:
        self.deps.view.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()

    def mouse_press(self, event: CanvasEvent) -> bool:
        if event.button == Qt.MouseButton.LeftButton:
            view = self.deps.view
            self._grab = event.view_pos
            self._seat = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
            view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        return True

    def mouse_move(self, event: CanvasEvent) -> bool:
        if self._grab is not None:
            view = self.deps.view
            travel = event.view_pos - self._grab
            view.horizontalScrollBar().setValue(round(self._seat[0] - travel.x()))
            view.verticalScrollBar().setValue(round(self._seat[1] - travel.y()))
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        self._grab = None
        self.deps.view.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A hand holding Space is panning, not making steps.

    def key_press(self, key: CanvasKey) -> bool:
        direction = PAN_KEYS.get(key.key)
        if direction is None:
            return False
        view = self.deps.view
        share = PAN_NUDGE if key.modifiers & Qt.KeyboardModifier.ShiftModifier else PAN_PAGE
        across, down = view.horizontalScrollBar(), view.verticalScrollBar()
        across.setValue(across.value() + round(direction[0] * view.viewport().width() * share))
        down.setValue(down.value() + round(direction[1] * view.viewport().height() * share))
        return True


class GestureMode(ModeBase):
    """A mode that lives for one drag of something the canvas draws.

    It holds what it moves, so a sync from the model — an agent's write, an undo — leaves
    that geometry alone until the release; Escape puts everything back where the press
    found it; and the release reports what happened and pops. A subclass says what it
    holds, how to put it back, what the pointer looks like meanwhile, and what the release
    means — the card resize and the drag of one side of a cut (a divide, a contract).
    """

    # The viewport's cursor while the gesture lasts; None leaves it alone.
    cursor: Qt.CursorShape | None = None

    def held(self) -> set[StepId]:
        """The steps whose geometry this gesture owns."""
        return set()

    def restore(self) -> None:
        """Put everything back where the press found it — Escape's half of the gesture."""

    def enter(self) -> None:
        self.deps.canvas.hold(self.held())
        if self.cursor is not None:
            self.deps.view.viewport().setCursor(self.cursor)

    def exit(self) -> None:
        if self.cursor is not None:
            self.deps.view.viewport().unsetCursor()
        self.deps.canvas.release()

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            self.restore()
            self.pop()
            return True
        return False

    def pop(self) -> None:
        if self.stack is not None:
            self.stack.pop()


class NodeResizeMode(GestureMode):
    """A card grabbed by an edge or a corner. Lives for one resize; Esc puts it back.

    The edge under the pointer is what moves and the opposite one stays put, so a card
    grows the way a window does — from the left, its seat moves with it. Each moved edge
    snaps while Snap to Grid is on, and no side goes below its minimum: the far edge is
    the limit, never the pointer.
    """

    name = NODE_RESIZE

    def __init__(self, deps: ModeDeps, node: StepNodeItem, edge: str) -> None:
        super().__init__(deps)
        self._node = node
        self._parts = edge.split("-")
        self.cursor = RESIZE_CURSORS[edge]
        self._was_pos = node.pos()
        self._was_size = node.footprint()
        self._seat = QRectF(node.pos(), QSizeF(*node.size()))
        # A playbook strip under the card is the card's own to add: the footprint is less it.
        self._playbook_h = node.size()[1] - node.footprint()[1]

    def held(self) -> set[StepId]:
        # A card in a stack moves the cards under it as it grows: the column is held whole.
        stack = self._node.stack
        return {self._node.step_id} if stack is None else set(stack.members)

    def restore(self) -> None:
        self._node.set_size(*self._was_size)
        self._node.setPos(self._was_pos)

    def mouse_move(self, event: CanvasEvent) -> bool:
        snap = self.deps.canvas.snap
        rect = QRectF(self._seat)
        x, y = snap(event.scene_pos.x()), snap(event.scene_pos.y())
        # The least a card can be is its least body and the strip it wears, if any.
        strip = self._node.size()[1] - self._node.body_size()[1]
        if "left" in self._parts:
            rect.setLeft(min(x, rect.right() - MIN_NODE_W))
        elif "right" in self._parts:
            rect.setRight(max(x, rect.left() + MIN_NODE_W))
        if "top" in self._parts:
            rect.setTop(min(y, rect.bottom() - MIN_NODE_H - strip))
        elif "bottom" in self._parts:
            rect.setBottom(max(y, rect.top() + MIN_NODE_H + strip))
        self._node.set_size(rect.width(), rect.height() - self._playbook_h)
        self._node.setPos(rect.topLeft())
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        at = self._node.pos()
        if at != self._was_pos or self._node.footprint() != self._was_size:
            # The step stores its body: the strip is the branch's, never the card's own.
            w, h = self._node.body_size()
            self.deps.canvas.node_resized.emit(self._node.step_id, at.x(), at.y(), w, h)
        self.pop()
        return True


class BlockDragMode(GestureMode):
    """The pick dragged as blocks: a stack moves whole, and a card on its own moves itself.

    Qt's own item drag moves cards one by one, so it cannot keep a stack a column; this
    mode moves each block's anchor — a stack's first card, or a loose card — by the
    pointer's travel, and every stack's frame lays its column under its first card as it
    goes (``StackItem.follow``). It starts wherever a press means the stack: its frame, any
    of its cards, or a picked card while the pick holds a stack.

    A press picks what it landed on unless that is already picked, as Qt's does, so what
    moves is always the pick; a press that never travels past the drag distance is a click,
    and a click leaves ``click`` picked — the card pressed, as Qt's click narrows to it, or
    nothing more for a frame, whose press already picked its stack. The release reports the
    anchors through ``nodes_moved``, where a member's seat is its stack's; Escape puts every
    block back.
    """

    name = BLOCK_DRAG
    cursor = Qt.CursorShape.ClosedHandCursor

    def __init__(
        self, deps: ModeDeps, grab: CanvasEvent, click: Sequence[StepId] | None = None
    ) -> None:
        super().__init__(deps)
        self._grab = grab
        self._click = None if click is None else list(click)
        self._dragging = False
        canvas = deps.canvas
        anchors: dict[StepId, None] = {}
        held: set[StepId] = set()
        for step_id in canvas.selection().steps:
            node = canvas.node(step_id)
            if node is None or node.pinned:
                continue  # A derived seat is nobody's to drag; a press on it is a click.
            stack = node.stack
            anchors[step_id if stack is None else stack.head] = None
            held.update((step_id,) if stack is None else stack.members)
        self._held = held
        self._from = {
            anchor: node.pos() for anchor in anchors if (node := canvas.node(anchor)) is not None
        }

    def held(self) -> set[StepId]:
        return self._held

    def restore(self) -> None:
        self._place(QPointF())

    def mouse_move(self, event: CanvasEvent) -> bool:
        travel = event.view_pos - self._grab.view_pos
        if not self._dragging and travel.manhattanLength() < QApplication.startDragDistance():
            return True
        self._dragging = True
        self._place(event.scene_pos - self._grab.scene_pos)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        canvas = self.deps.canvas
        moved = [
            (anchor, node.pos().x(), node.pos().y())
            for anchor, was in self._from.items()
            if (node := canvas.node(anchor)) is not None and node.pos() != was
        ]
        if moved:
            canvas.nodes_moved.emit(moved)
        elif not self._dragging and self._click is not None:
            canvas.select_steps(self._click)
        self.pop()
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A press in flight is a drag or a click; the double click comes after.

    def _place(self, travel: QPointF) -> None:
        # Each card snaps itself as it lands (StepNodeItem.itemChange), as under Qt's drag.
        for anchor, was in self._from.items():
            node = self.deps.canvas.node(anchor)
            if node is not None:
                node.setPos(was + travel)


def drag_the_pick(
    deps: ModeDeps, event: CanvasEvent, node: StepNodeItem | None, stack: Stack | None
) -> BlockDragMode | None:
    """The block drag a press starts, having picked what the press landed on — or None when
    the press is Qt's: a loose card picked among other loose cards.

    A press on a stacked card picks it unless it is picked already, the way Qt's press does;
    a press on a frame picks every member of its stack, added to the pick with Ctrl or Shift
    held. A loose card the press leaves alone in the pick is ``RestackMode``'s, never this.
    """
    canvas = deps.canvas
    picked = list(canvas.selection().steps)
    if node is not None:
        if node.step_id not in picked:
            canvas.select_steps([node.step_id])
        elif node.stack is None and not any(
            (other := canvas.node(step_id)) is not None and other.stack is not None
            for step_id in picked
        ):
            return None
        return BlockDragMode(deps, event, click=[node.step_id])
    assert stack is not None
    adding = event.modifiers & (
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    if adding:
        canvas.select_steps([*picked, *(m for m in stack.members if m not in picked)])
    elif not set(stack.members) <= set(picked):
        canvas.select_steps(list(stack.members))
    return BlockDragMode(deps, event)


@dataclass
class _Glide:
    """A card easing from where it stood to where the column wants it now."""

    start: QPointF
    end: QPointF
    elapsed: float = 0.0

    def at(self) -> QPointF:
        eased = out_cubic(span(self.elapsed, 0.0, MAKE_WAY_S))
        return self.start + (self.end - self.start) * eased

    def done(self) -> bool:
        return self.elapsed >= MAKE_WAY_S


class RestackMode(GestureMode):
    """One card dragged into, through or out of a stack, the cards making way for it: any
    card Shift-dragged, and a loose card dragged on its own.

    The card follows the hand, and its *centre* says where it is. Inside a frame grown by
    the frame's pad — its own stack's before any other — it takes the slot whose gap is
    nearest, and the other cards ease aside to open that gap, so the drop is visible before
    it happens. Out past its own frame's pad it is *leaving*: the column closes up without
    it and the frame lets go. A loose card over a stack joins it the same way, and over
    nothing is only moved, saying nothing. A card in a stack, or joining one, is lifted out
    of its arrows — every drop rewires them, and drawn meanwhile they would run to where it
    no longer stands. Every gap is ``member_seats`` over the order the drop would make, from
    the columns as they stood at the press, so what the hand sees never feeds back into
    which slot it is at.

    The motion is the one slide the canvas allows (DESIGN.md's *Focus and motion*): a card
    that moves glides for ``MAKE_WAY_S`` on one :class:`FrameClock` this mode owns, which
    runs only while a card is gliding and is stopped and deleted on exit; ``settle()`` ends
    every glide at once, for a test or a render.

    Whether a stack may be reordered or joined is the model's (``stack_refusal``): a refused
    stack opens no gap, the status line says why, and letting go there does nothing. The
    release reports only where the card went — into a stack at a slot, or out of its own at
    a seat — and the activity asks the model which verb that is.
    """

    name = RESTACK
    cursor = Qt.CursorShape.ClosedHandCursor

    def __init__(self, deps: ModeDeps, grab: CanvasEvent, node: StepNodeItem) -> None:
        super().__init__(deps)
        canvas = deps.canvas
        self._grab = grab
        self._card = node.step_id
        self._home = node.stack
        self._stacks = {stack.id: stack for stack in canvas.stacks()}
        held = {self._card, *(m for stack in self._stacks.values() for m in stack.members)}
        nodes = {step_id: n for step_id in held if (n := canvas.node(step_id)) is not None}
        self._seats = {step_id: n.pos() for step_id, n in nodes.items()}
        self._sizes = {step_id: n.size() for step_id, n in nodes.items()}
        self._frames = {
            stack_id: item.frame_scene_rect()
            for stack_id in self._stacks
            if (item := canvas.frame(stack_id)) is not None
        }
        self._dragging = False
        # Why the card's own stack may not be reordered — asked once, as the drag begins.
        self._stuck: str | None = None
        self._refusals: dict[str, str | None] = {}
        # Where the card is aimed — a stack's id and a slot, or None — what letting go there
        # reports, and where the card then stands.
        self._aimed: tuple[str | None, int] | None = None
        self._drop: Callable[[], None] | None = None
        self._landing: QPointF | None = None
        # The frames this gesture has borrowed, and whether it ended in a drop.
        self._stood: set[str] = set()
        self._landed = False
        self._glides: dict[StepId, _Glide] = {}
        self._clock = FrameClock(deps.view)
        self._unsubscribe = self._clock.ticked.connect(self._tick)

    def held(self) -> set[StepId]:
        return set(self._seats)

    def restore(self) -> None:
        self._glides.clear()
        self._clock.stop()
        for step_id, seat in self._seats.items():
            node = self.deps.canvas.node(step_id)
            if node is not None:
                node.setPos(seat)

    def exit(self) -> None:
        self._unsubscribe()
        self._clock.stop()
        self._clock.deleteLater()
        canvas = self.deps.canvas
        canvas.lift_links(None)
        for stack_id in self._stood:
            item = canvas.frame(stack_id)
            if item is not None:
                item.free(lay=not self._landed)
        super().exit()

    def moving(self) -> bool:
        """Whether a card is still gliding — the clock runs exactly while one is."""
        return bool(self._glides)

    def settle(self) -> None:
        """Every glide at its end, now."""
        for step_id, glide in self._glides.items():
            node = self.deps.canvas.node(step_id)
            if node is not None:
                node.setPos(glide.end)
        self._glides.clear()
        self._clock.stop()

    def mouse_move(self, event: CanvasEvent) -> bool:
        if not self._dragging:
            travel = event.view_pos - self._grab.view_pos
            if travel.manhattanLength() < QApplication.startDragDistance():
                return True
            self._dragging = True
            if self._home is not None:
                self._stuck = self.deps.canvas.stack_refusal(self._home, None)
                if self._stuck is not None:
                    self.deps.status(f"Cannot move {self._name()} — {self._stuck}")
                else:
                    # Borrowed before the card moves, or its frame would lay it straight back.
                    self._arrange(self._home, self._home.members)
        node = self.deps.canvas.node(self._card)
        if self._stuck is not None or node is None:
            return True
        node.setPos(self._seats[self._card] + event.scene_pos - self._grab.scene_pos)
        centre = node.body_scene_rect().center()
        target = self._target(centre)
        aim = (None, 0) if target is None else (target.id, self._slot(target, centre.y()))
        if aim != self._aimed:
            self._aimed = aim
            self._aim(target, aim[1])
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        drop = self._drop
        if drop is None:
            self.restore()
        else:
            self.settle()
            node = self.deps.canvas.node(self._card)
            if node is not None and self._landing is not None:
                node.setPos(self._landing)
            self._landed = True
        # Popped before reporting, so the command's sync finds nothing held.
        self.pop()
        if drop is not None:
            drop()
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A press in flight is a drag or a click; the double click comes after.

    # -- where the card is -----------------------------------------------------------------

    def _target(self, centre: QPointF) -> Stack | None:
        """The stack whose frame, grown by its pad, holds the card's centre."""
        home = None if self._home is None else self._home.id
        for stack_id in sorted(self._frames, key=lambda stack_id: stack_id != home):
            grown = self._frames[stack_id].adjusted(-FRAME_PAD, -FRAME_PAD, FRAME_PAD, FRAME_PAD)
            if grown.contains(centre):
                return self._stacks[stack_id]
        return None

    def _slot(self, stack: Stack, centre_y: float) -> int:
        """The slot whose gap's middle is nearest the card's."""
        rest = self._without_card(stack)
        half = self._sizes[self._card][1] / 2

        def miss(slot: int) -> float:
            return abs(
                self._column(stack, _at(rest, slot, self._card))[self._card].y() + half - centre_y
            )

        return min(range(len(rest) + 1), key=miss)

    def _aim(self, target: Stack | None, slot: int) -> None:
        """Lay every stack the card has touched out as letting go now would leave it, and
        work out what letting go reports."""
        canvas, card, home = self.deps.canvas, self._card, self._home
        refusal = None
        if target is not None and (home is None or target.id != home.id):
            if target.id not in self._refusals:
                self._refusals[target.id] = canvas.stack_refusal(target, card)
            refusal = self._refusals[target.id]
        moving = target is not None and home is not None and target.id == home.id
        joining = target is not None and not moving and refusal is None
        leaving = home is not None and target is None
        orders: dict[str, tuple[StepId, ...]] = {}
        if home is not None:
            rest = self._without_card(home)
            orders[home.id] = _at(rest, slot, card) if moving else rest if leaving else home.members
        if joining and target is not None:
            orders[target.id] = _at(target.members, slot, card)
        for stack_id in self._stood - orders.keys():
            orders[stack_id] = self._stacks[stack_id].members
        for stack_id, order in orders.items():
            self._arrange(self._stacks[stack_id], order)
        # A stacked card's arrows, or a joining one's, change whatever the drop: not drawn.
        canvas.lift_links(card if home is not None or joining else None)

        name = self._name()
        self._drop, self._landing = None, None
        if refusal is not None:
            self.deps.status(f"Cannot put {name} in that stack — {refusal}")
        elif target is not None:
            order = orders[target.id]
            self._landing = self._column(target, order)[card]
            if order != target.members:
                stack_id = target.id
                self._drop = lambda: canvas.dropped_into_stack.emit(card, stack_id, slot)
            place = f"{name} goes {slot + 1} of {len(order)}"
            self.deps.status(
                f"Reorder: {place}. Out of the frame takes it out; Esc cancels."
                if moving
                else f"Add to stack: {place}, without its links. Esc cancels."
            )
        elif leaving:
            self._drop = self._report_out
            self.deps.status(f"Take out: let go to leave {name} here, with no links. Esc cancels.")
        else:
            # A plain move — and what an aim at a stack said a moment ago no longer holds.
            self._drop = self._report_moved
            self.deps.status("")

    def _arrange(self, stack: Stack, order: tuple[StepId, ...]) -> None:
        """The stack's cards gliding to the column ``order`` makes, and its frame round it."""
        item = self.deps.canvas.frame(stack.id)
        if item is None:
            return
        self._stood.add(stack.id)
        if not order:
            item.stand(QRectF())
            return
        for step_id, seat in self._column(stack, order).items():
            if step_id != self._card:
                self._glide(step_id, seat)
        head = self._seats[stack.head]
        rect = frame(Stack(stack.id, order), (head.x(), head.y()), self._sizes.__getitem__)
        item.stand(QRectF(*rect))

    def _column(self, stack: Stack, order: tuple[StepId, ...]) -> dict[StepId, QPointF]:
        """Where each card of ``order`` would stand, under the stack's seat at the press."""
        head = self._seats[stack.head]
        seats = member_seats(Stack(stack.id, order), (head.x(), head.y()), self._sizes.__getitem__)
        return {step_id: QPointF(x, y) for step_id, (x, y) in seats.items()}

    def _without_card(self, stack: Stack) -> tuple[StepId, ...]:
        return tuple(member for member in stack.members if member != self._card)

    # -- the make-way motion -------------------------------------------------------------------

    def _glide(self, step_id: StepId, end: QPointF) -> None:
        node = self.deps.canvas.node(step_id)
        glide = self._glides.get(step_id)
        if node is None or (glide is not None and glide.end == end):
            return
        if node.pos() == end:
            self._glides.pop(step_id, None)
        else:
            self._glides[step_id] = _Glide(node.pos(), end)
            self._clock.start()

    def _tick(self, dt: float) -> None:
        for step_id, glide in list(self._glides.items()):
            glide.elapsed += dt
            node = self.deps.canvas.node(step_id)
            if node is not None:
                node.setPos(glide.at())
            if glide.done():
                del self._glides[step_id]
        if not self._glides:
            self._clock.stop()

    # -- what letting go reports ---------------------------------------------------------------

    def _report_out(self) -> None:
        node = self.deps.canvas.node(self._card)
        if node is not None:
            self.deps.canvas.dropped_out_of_stack.emit(self._card, node.pos().x(), node.pos().y())

    def _report_moved(self) -> None:
        node = self.deps.canvas.node(self._card)
        if node is not None and node.pos() != self._seats[self._card]:
            self.deps.canvas.nodes_moved.emit([(self._card, node.pos().x(), node.pos().y())])

    def _name(self) -> str:
        node = self.deps.canvas.node(self._card)
        return node.name() if node is not None else ""


def _at(order: Sequence[StepId], slot: int, step_id: StepId) -> tuple[StepId, ...]:
    """``order`` with ``step_id`` put in at ``slot``."""
    return (*order[:slot], step_id, *order[slot:])


class LassoMode(ModeBase):
    """Draw round the steps to pick: every card the outline touches is selected.

    A rubber band is a box, and a cluster on a busy canvas rarely is. One lasso ends the
    mode, like one link ends connect; Shift held on the release adds the catch to what was
    already selected rather than replacing it. A press that never moves is a click, and a
    click here means nothing — the selection is left as it was.
    """

    name = LASSO

    def __init__(self, deps: ModeDeps) -> None:
        super().__init__(deps)
        self._path: QPainterPath | None = None

    def enter(self) -> None:
        self.deps.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.deps.status("Lasso: draw round the steps to pick. Shift adds, Esc leaves.")

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.hide_outline()

    def mouse_press(self, event: CanvasEvent) -> bool:
        if event.button == Qt.MouseButton.LeftButton:
            self._path = QPainterPath(event.scene_pos)
        return True

    def mouse_move(self, event: CanvasEvent) -> bool:
        if self._path is not None:
            self._path.lineTo(event.scene_pos)
            self.deps.canvas.aim_outline(self._path)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        path = self._path
        self._path = None
        if path is None:
            return True
        self.deps.canvas.hide_outline()
        extent = path.boundingRect()
        if extent.width() >= HANDLE_GRAB or extent.height() >= HANDLE_GRAB:
            path.closeSubpath()
            picked = [node.step_id for node in self.deps.canvas.nodes_touching(path)]
            if event.modifiers & Qt.KeyboardModifier.ShiftModifier:
                kept = list(self.deps.canvas.selection().steps)
                picked = kept + [step_id for step_id in picked if step_id not in kept]
            self.deps.canvas.select_steps(picked)
        if self.stack is not None:
            self.stack.pop()
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # No step-creating double clicks while drawing.

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape and self._path is not None:
            # Mid-draw: drop the outline and stay, the way connect drops a pending step.
            self._path = None
            self.deps.canvas.hide_outline()
            return True
        return False  # Nothing pending: the canvas pops the mode instead.


def _along(orientation: Qt.Orientation, point: QPointF) -> float:
    """The coordinate a cut works in: x across a vertical line, y across a horizontal."""
    return point.x() if orientation == Qt.Orientation.Vertical else point.y()


def cut_band(
    orientation: Qt.Orientation, cut: float, delta: float, visible: QRectF
) -> QPainterPath:
    """The outline a cut shows: the line, and the room opened or closed beside it.

    A rectangle from the cut to where the side has travelled, spanning the visible canvas
    the other way — edge to edge — so before a press it is a line under the cursor, and
    during the drag it is the band the moving side has crossed: the room a divide makes,
    the gap a contract closes.
    """
    low, high = min(cut, cut + delta), max(cut, cut + delta)
    path = QPainterPath()
    if orientation == Qt.Orientation.Vertical:
        path.addRect(QRectF(low, visible.top(), high - low, visible.height()))
    else:
        path.addRect(QRectF(visible.left(), low, visible.width(), high - low))
    return path


class _CutMode(ModeBase):
    """Lay a cut under the cursor from edge to edge — vertical or horizontal, the mode's
    choice — and on a press fix it there and hand over to the drag, which takes this mode's
    place: one cut ends the mode, like one lasso ends that one, and Escape mid-drag leaves
    the way it leaves a resize. Before the press Escape leaves too; the canvas pops the
    mode, since nothing here is pending. A subclass says what it is called, what the status
    line asks for, and which drag the press starts.
    """

    # The mode's name by the line it cuts with — the drag it starts carries the same one, so
    # the verb that entered the mode stays checked until the gesture ends.
    names: ClassVar[Mapping[Qt.Orientation, str]]

    def __init__(self, deps: ModeDeps, orientation: Qt.Orientation) -> None:
        super().__init__(deps)
        self._orientation = orientation
        self.name = self.names[orientation]

    def prompt(self) -> str:
        raise NotImplementedError

    def drag(self, cut: float) -> GestureMode:
        raise NotImplementedError

    def enter(self) -> None:
        self.deps.view.viewport().setCursor(CUT_CURSORS[self._orientation])
        self.deps.status(self.prompt())

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.hide_outline()

    def mouse_press(self, event: CanvasEvent) -> bool:
        if event.button == Qt.MouseButton.LeftButton and self.stack is not None:
            cut = _along(self._orientation, event.scene_pos)
            stack = self.stack
            stack.pop()  # This mode is done; the drag is the rest of the gesture.
            stack.push(self.drag(cut))
        return True

    def mouse_move(self, event: CanvasEvent) -> bool:
        cut = _along(self._orientation, event.scene_pos)
        self.deps.canvas.aim_outline(
            cut_band(self._orientation, cut, 0.0, visible_scene_rect(self.deps.view))
        )
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # No step-creating double clicks while placing a cut.

    def _ways(self) -> str:
        return "left or right" if self._orientation == Qt.Orientation.Vertical else "up or down"


class _CutDragMode(GestureMode):
    """The drag half of a cut: one side of it moves along the cut's axis as the pointer
    does, by the rule a subclass names — a Qt-free function of the seats at the press, the
    cut and the snapped distance, so the ``layout`` verb that runs the same rule cannot
    disagree with the drag.

    Every card is held, both sides, since either may move before the release, and each
    card's seat and size are taken at the press: which side a card is on is its centre
    then, so a drag back past the cut flips cleanly with no state to clear. The band drawn
    beside the cut is how far the side has travelled. The rule moves blocks, not cards: a
    stack is packed into its frame, so it goes to the side its frame's centre is on and
    travels whole.
    """

    names: ClassVar[Mapping[Qt.Orientation, str]]

    def __init__(self, deps: ModeDeps, orientation: Qt.Orientation, cut: float) -> None:
        super().__init__(deps)
        self._orientation = orientation
        self.name = self.names[orientation]
        # The geometry's word for the same thing: a vertical line moves a side along x.
        self._axis: Axis = "x" if orientation == Qt.Orientation.Vertical else "y"
        self.cursor = CUT_CURSORS[orientation]
        self._cut = cut
        nodes = deps.canvas.nodes()
        self._cards: dict[StepId, Point] = {
            node.step_id: (node.pos().x(), node.pos().y()) for node in nodes
        }
        self._packing = Packing(deps.canvas.stacks(), {node.step_id: node.size() for node in nodes})
        self._placed = self._packing.blocks(self._cards)
        self._sizes = self._packing.sizes
        self._moved: dict[StepId, Point] = {}
        self._travel = 0.0

    def follow(self, delta: float) -> tuple[dict[StepId, Point], float]:
        """The seats that move for a drag this far, and how far the side travels."""
        raise NotImplementedError

    def report(self, moved: list[tuple[StepId, float, float]]) -> None:
        """What the release means: which of the canvas's signals carries the moved seats."""
        raise NotImplementedError

    def held(self) -> set[StepId]:
        return set(self._cards)

    def restore(self) -> None:
        self._moved, self._travel = {}, 0.0
        self._place()

    def enter(self) -> None:
        super().enter()
        self._aim()

    def exit(self) -> None:
        super().exit()
        self.deps.canvas.hide_outline()

    def mouse_move(self, event: CanvasEvent) -> bool:
        delta = self.deps.canvas.snap(_along(self._orientation, event.scene_pos) - self._cut)
        self._moved, self._travel = self.follow(delta)
        self._place()
        self._aim()
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        if self._moved:
            moved = self._packing.unfold(self._moved)
            self.report([(step_id, x, y) for step_id, (x, y) in moved.items()])
        self.pop()
        return True

    def _place(self) -> None:
        moved = self._packing.unfold(self._moved)
        for step_id, seat in self._cards.items():
            node = self.deps.canvas.node(step_id)
            if node is not None:
                node.setPos(QPointF(*moved.get(step_id, seat)))

    def _aim(self) -> None:
        self.deps.canvas.aim_outline(
            cut_band(self._orientation, self._cut, self._travel, visible_scene_rect(self.deps.view))
        )


class DivideMode(_CutMode):
    """Cut the graph along a line and push one side away, to make room in the middle."""

    names = DIVIDE_NAMES

    def prompt(self) -> str:
        return f"Divide: press to place the cut, drag {self._ways()} to push that side. Esc leaves."

    def drag(self, cut: float) -> GestureMode:
        return DivideDragMode(self.deps, self._orientation, cut)


class DivideDragMode(_CutDragMode):
    """The drag half of a divide: every card on the side dragged towards moves with the
    pointer — ``geometry.shift``, which ``dplanner layout shift`` runs too."""

    names = DIVIDE_NAMES

    def follow(self, delta: float) -> tuple[dict[StepId, Point], float]:
        return shift(self._placed, self._sizes, self._axis, self._cut, delta), delta

    def report(self, moved: list[tuple[StepId, float, float]]) -> None:
        self.deps.canvas.graph_divided.emit(moved)


class ContractMode(_CutMode):
    """Cut the graph along a line and pull one side up to the other, to close a hole —
    Divide's other half."""

    names = CONTRACT_NAMES

    def prompt(self) -> str:
        return (
            f"Contract: press to place the cut, drag {self._ways()} to close up that way."
            " Esc leaves."
        )

    def drag(self, cut: float) -> GestureMode:
        return ContractDragMode(self.deps, self._orientation, cut)


class ContractDragMode(_CutDragMode):
    """The drag half of a contract: the side behind the pointer is pulled after it, and
    stops the sorts' gap short of the first card ahead of it in its band — clamped live by
    ``geometry.contract``, which ``dplanner layout contract`` runs too. The status line
    names the pair that stopped it, since a drag that will not go further says why."""

    names = CONTRACT_NAMES

    def follow(self, delta: float) -> tuple[dict[StepId, Point], float]:
        done = contract(self._placed, self._sizes, self._axis, self._cut, delta)
        if done.stopped is not None:
            mover, met = (self._name(step_id) for step_id in done.stopped)
            self.deps.status(f"Contract: {mover} stops one gap from {met}.")
        elif done.moved:
            count = len(done.moved)
            self.deps.status(
                f"Contract: pulling {count} step{'s' if count != 1 else ''}"
                f" {direction(self._axis, done.by)}."
            )
        return done.moved, done.by

    def report(self, moved: list[tuple[StepId, float, float]]) -> None:
        self.deps.canvas.graph_contracted.emit(moved)

    def _name(self, step_id: StepId) -> str:
        node = self.deps.canvas.node(step_id)
        return node.name() if node is not None else ""


def visible_scene_rect(view: QGraphicsView) -> QRectF:
    """The part of the plane the viewport shows — what "edge to edge" means to a mode."""
    return view.mapToScene(view.viewport().rect()).boundingRect()


class StripPressMode(ModeBase):
    """A press on a card's playbook strip, which is a button and not a handle: let go on the
    strip, it asks for the step's pass in Step Details (``playbook_opened``); anywhere else,
    nothing. Nothing drags from it — the strip is not the card's footprint, so a card is
    taken by its body."""

    name = STRIP_PRESS

    def __init__(self, deps: ModeDeps, node: StepNodeItem) -> None:
        super().__init__(deps)
        self._node = node

    def mouse_move(self, event: CanvasEvent) -> bool:
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        if self.stack is not None:
            self.stack.pop()
        if self._node.playbook_tip_at(event.scene_pos):
            self.deps.canvas.playbook_opened.emit(self._node.step_id)
        return True

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape and self.stack is not None:
            self.stack.pop()
            return True
        return False


class IdleMode(ModeBase):
    """The base. Qt does selection, rubber banding and the drag of several loose cards; this
    catches the rest: every right press, and a left press on a card's link handle, a stack's
    "+", a card's resize band, any card with Shift held or a loose card on its own, a card
    in a stack, and a stack's frame — in that order, each before the next may claim the
    point. An arrow drawn over a frame is Qt's to pick. A pinned card — Wave view's, whose
    seat is derived — is picked by the same presses and moved by none: it has no resize band,
    nothing restacks it, and a block drag holds it still."""

    name = IDLE

    def mouse_press(self, event: CanvasEvent) -> bool:
        if event.button == Qt.MouseButton.RightButton:
            # The context menu decides what a right-click picks. Handed to Qt, a right press
            # on an arrow — selectable, not movable — clears the whole selection first.
            return True
        canvas = self.deps.canvas
        node = canvas.node_at(event.scene_pos)
        if node is not None and node.is_over_handle(event.scene_pos):
            # Claimed before Qt sees it, so the press starts neither a move nor a rubber band.
            self._push(LinkDragMode(self.deps, node.step_id))
            return True
        if event.button != Qt.MouseButton.LeftButton:
            return False
        added = canvas.add_at(event.scene_pos)
        if added is not None:
            canvas.stack_add_requested.emit(added.members[-1])
            return True
        if node is not None:
            edge = node.edge_at(event.scene_pos)
            if edge:
                self._push(NodeResizeMode(self.deps, node, edge))
                return True
            if node.playbook_tip_at(event.scene_pos) and not event.modifiers:
                canvas.select_step(node.step_id)
                return self._push(StripPressMode(self.deps, node))
            if event.modifiers & Qt.KeyboardModifier.ControlModifier:
                return False  # Qt's toggle of one card in the pick.
            # The one card into, through or out of a stack: Shift on any card, and a loose
            # card the press leaves alone in the pick — a press outside the pick narrows it,
            # as Qt's would. A press that never travels is a click, and picks it. Never a
            # pinned card: its seat is derived, and nothing a drag did would be kept.
            picked = canvas.selection().steps
            alone = node.stack is None and (node.step_id not in picked or len(picked) == 1)
            restacks = alone or event.modifiers & Qt.KeyboardModifier.ShiftModifier
            if restacks and not node.pinned:
                canvas.select_steps([node.step_id])
                return self._push(RestackMode(self.deps, event, node))
            return self._push(drag_the_pick(self.deps, event, node, None))
        stack = canvas.frame_at(event.scene_pos)
        return stack is not None and self._push(drag_the_pick(self.deps, event, None, stack))

    def mouse_move(self, event: CanvasEvent) -> bool:
        """Feedback only — the event still falls through to Qt, which hovers and drags. A
        card's frame shows the resize arrows so the gesture can be found, the handle winning
        its corner of the right edge as it does on the press; a stack's "+" shows a pointing
        hand, and its frame an open one: room to take hold of. The stack under the pointer
        says what Shift does to its cards."""
        if event.buttons == Qt.MouseButton.NoButton:
            canvas = self.deps.canvas
            canvas.hint_at(event.scene_pos)
            node = canvas.node_at(event.scene_pos)
            cursor: Qt.CursorShape | None = None
            if canvas.add_at(event.scene_pos) is not None:
                cursor = Qt.CursorShape.PointingHandCursor
            elif node is not None:
                edge = "" if node.is_over_handle(event.scene_pos) else node.edge_at(event.scene_pos)
                cursor = RESIZE_CURSORS[edge] if edge else None
            elif (framed := canvas.frame_at(event.scene_pos)) is not None:
                head = canvas.node(framed.head)
                cursor = None if head is not None and head.pinned else Qt.CursorShape.OpenHandCursor
            viewport = self.deps.view.viewport()
            if cursor is not None:
                if viewport.cursor().shape() != cursor:
                    viewport.setCursor(cursor)
            elif viewport.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
                viewport.unsetCursor()
        return False

    def double_click(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.node_at(event.scene_pos)
        if node is not None:
            # A gesture is not a special case: select, then run the same verb the menu does.
            self.deps.canvas.select_step(node.step_id)
            self.deps.run_action("steps.details")
            return True
        if self.deps.canvas.frame_at(event.scene_pos) is not None:
            return True  # A stack's frame is the stack's, never room for a new step.
        point = event.scene_pos
        self.deps.canvas.create_requested.emit(*centred_on(point.x(), point.y()))
        return True

    def _push(self, mode: ModeBase | None) -> bool:
        """Start ``mode``, if there is one: True when the press is now a mode's."""
        if mode is None or self.stack is None:
            return False
        self.stack.push(mode)
        return True
