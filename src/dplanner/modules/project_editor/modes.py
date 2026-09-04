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

:class:`Canvas` is the whole of a mode's power over the canvas, which is why it is written
out rather than inferred from passing the scene around: a mode can be driven in a test by
anything that satisfies it, and a new mode cannot quietly grow a reach nobody sanctioned.

All of them live in this one file because a mode is only worth reading beside the others —
what each one claims is what the next one therefore never sees. Split it when a single mode
outgrows a screen, not when the file does.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsView

from dplanner.core.signals import Signal
from dplanner.domain.model import StepId
from dplanner.modules.project_editor.items import HANDLE_GRAB, StepNodeItem
from dplanner.modules.project_editor.positions import MIN_NODE_H, MIN_NODE_W, centred_on
from dplanner.modules.project_editor.region_items import REGION_RADIUS, RegionItem
from dplanner.modules.project_editor.regions import MIN_REGION
from dplanner.modules.project_editor.renderers import RenderHints
from dplanner.modules.project_editor.selection import CanvasSelection

# How the current mode reaches the context, so an action's ``state`` can read it as a pure
# function — which is what makes the Connect toolbar button check itself for free.
MODE_URI_PREFIX = "app://canvas-mode/"

IDLE = "idle"
CONNECT = "connect"
PAN = "pan"
LINK_DRAG = "link-drag"
REGION_CREATE = "region-create"
REGION_DRAG = "region-drag"
REGION_RESIZE = "region-resize"
NODE_RESIZE = "node-resize"
LASSO = "lasso"


def mode_uri(name: str) -> str:
    return f"{MODE_URI_PREFIX}{name}"


# What each mode wants every node to show, fanned out by the scene when the stack changes.
# Kept beside the mode names so a new mode decides its look in the same breath. Connect
# shows every handle — each is a target; pan, lasso and the region modes hide them — their
# presses do not link. Anything unlisted gets the default (idle's hover-only handle).
HINTS_BY_MODE = {
    CONNECT: RenderHints(handles="always"),
    PAN: RenderHints(handles="hidden"),
    REGION_CREATE: RenderHints(handles="hidden"),
    REGION_DRAG: RenderHints(handles="hidden"),
    REGION_RESIZE: RenderHints(handles="hidden"),
    NODE_RESIZE: RenderHints(handles="hidden"),
    LASSO: RenderHints(handles="hidden"),
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


# -- what a mode is handed ---------------------------------------------------------------------


@dataclass(frozen=True)
class CanvasEvent:
    """A mouse event in scene coordinates, with the widget left out on purpose."""

    scene_pos: QPointF
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

    link_requested: Signal[StepId, StepId]
    create_requested: Signal[float, float]
    selection_changed: Signal[CanvasSelection]
    region_create_requested: Signal[float, float, float, float]
    # Regions that finished moving, with the steps they carried — one gesture, one emission.
    regions_moved: Signal[list[tuple[str, float, float]], list[tuple[StepId, float, float]]]
    region_resized: Signal[str, float, float, float, float]
    # A card that finished resizing: its new seat and size, since an edge may have moved.
    node_resized: Signal[StepId, float, float, float, float]

    def node_at(self, scene_pos: QPointF) -> StepNodeItem | None: ...

    def node(self, step_id: StepId) -> StepNodeItem | None: ...

    def select_step(self, step_id: StepId | None) -> None: ...

    def select_steps(self, step_ids: list[StepId]) -> None: ...

    def selected_step(self) -> StepId | None: ...

    def selection(self) -> CanvasSelection: ...

    def nodes_touching(self, path: QPainterPath) -> list[StepNodeItem]: ...

    def link_refusal(self, waiter: StepId, source: StepId) -> str | None: ...

    def aim_preview(self, origin: QPointF, cursor: QPointF, ok: bool) -> None: ...

    def hide_preview(self) -> None: ...

    def set_link_states(self, valid: StepId | None, invalid: StepId | None) -> None: ...

    def region_at(self, scene_pos: QPointF) -> RegionItem | None: ...

    def select_region(self, region_id: str) -> None: ...

    def nodes_inside(self, region: RegionItem) -> list[StepNodeItem]: ...

    # The one outline a gesture drawing an area shows: a region's rectangle, a lasso's path.
    def aim_outline(self, path: QPainterPath) -> None: ...

    def hide_outline(self) -> None: ...

    # A coordinate on the grid while Snap to Grid is on, else itself: what every gesture
    # that produces a position or a size runs its numbers through.
    def snap(self, value: float) -> float: ...

    # A mode owns this region's geometry — and these steps' — until it releases: the
    # scene's sync leaves them where the gesture has them.
    def hold(self, region_id: str | None, step_ids: set[StepId]) -> None: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class CanvasDeps:
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

    def __init__(self, deps: CanvasDeps) -> None:
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
    """

    def _refusal(self, source: StepId, target: StepId) -> str | None:
        if source == target:
            return "a step cannot depend on itself"
        return self.deps.canvas.link_refusal(target, source)

    def _aim(self, source: StepId, cursor: QPointF) -> None:
        canvas = self.deps.canvas
        target = canvas.node_at(cursor)
        origin_node = canvas.node(source)
        if origin_node is None:
            return
        origin = origin_node.handle_scene_pos()
        ok = target is not None and self._refusal(source, target.step_id) is None
        if target is None or target.step_id == source:
            canvas.set_link_states(None, None)
        else:
            canvas.set_link_states(target.step_id if ok else None, None if ok else target.step_id)
        canvas.aim_preview(origin, cursor, ok)

    def _aim_at_step(self, source: StepId, target: StepId) -> None:
        """Aim at a whole node rather than at a point — what keyboard navigation produces."""
        canvas = self.deps.canvas
        origin_node, target_node = canvas.node(source), canvas.node(target)
        if origin_node is None or target_node is None:
            return
        ok = self._refusal(source, target) is None
        canvas.set_link_states(target if ok else None, None if ok else target)
        canvas.aim_preview(
            origin_node.handle_scene_pos(), target_node.sceneBoundingRect().center(), ok
        )

    def _propose(self, source: StepId, target: StepId) -> None:
        """Hand the pair to the activity, which runs ``steps.link`` exactly as the menu does."""
        self.deps.canvas.link_requested.emit(source, target)

    def _clear(self) -> None:
        self.deps.canvas.hide_preview()
        self.deps.canvas.set_link_states(None, None)


class LinkDragMode(_LinkingMode):
    """Dragging from a node's handle. Lives for exactly one drag and pops itself."""

    name = LINK_DRAG

    def __init__(self, deps: CanvasDeps, source: StepId) -> None:
        super().__init__(deps)
        self._source = source

    def enter(self) -> None:
        node = self.deps.canvas.node(self._source)
        if node is not None:
            self._aim(self._source, node.handle_scene_pos())

    def exit(self) -> None:
        self._clear()

    def mouse_move(self, event: CanvasEvent) -> bool:
        self._aim(self._source, event.scene_pos)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        target = self.deps.canvas.node_at(event.scene_pos)
        if target is not None and target.step_id != self._source:
            self._propose(self._source, target.step_id)
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
    """Pick a step, then the step that waits on it — with the mouse or with the keyboard.

    It adopts whatever is selected as its source, so entering the mode with a step in front
    of you means you are already halfway. Movement keys are *not* consumed: they fall through
    to the canvas keymap and move the selection, and this mode re-aims at wherever they
    landed. Enter finishes the link, and one finished link ends the mode.
    """

    name = CONNECT

    def __init__(self, deps: CanvasDeps) -> None:
        super().__init__(deps)
        self._source: StepId | None = None
        self._unsubscribe: Callable[[], None] | None = None

    def enter(self) -> None:
        self._unsubscribe = self.deps.canvas.selection_changed.connect(self._on_selection)
        self.deps.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._take_source(self.deps.canvas.selected_step())

    def exit(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.deps.view.viewport().unsetCursor()
        self._clear()

    def mouse_press(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.node_at(event.scene_pos)
        if node is None:
            self._take_source(None)
        elif self._source is None or node.step_id == self._source:
            self.deps.canvas.select_step(node.step_id)
            self._take_source(node.step_id)
        else:
            self._finish(node.step_id)
        return True  # Consumed either way: no node dragging and no rubber band in this mode.

    def mouse_move(self, event: CanvasEvent) -> bool:
        if self._source is not None:
            self._aim(self._source, event.scene_pos)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # A second click is the second step, never a new one.

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            if self._source is None:
                return False  # Nothing pending: the canvas pops the mode instead.
            self._take_source(None)
            return True
        if key.key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            target = self.deps.canvas.selected_step()
            if self._source is not None and target is not None and target != self._source:
                self._finish(target)
            return True
        return False  # Movement keys belong to the keymap; this mode follows what they select.

    def _take_source(self, step_id: StepId | None) -> None:
        self._source = step_id
        self._clear()
        if step_id is None:
            self.deps.status("Connect: pick the step others wait on. Esc leaves.")
        else:
            self.deps.status("Connect: pick the step that waits. Enter links, Esc cancels.")

    def _on_selection(self, selection: CanvasSelection) -> None:
        if self._source is None or len(selection.steps) != 1:
            return
        target = selection.steps[0]
        if target != self._source:
            self._aim_at_step(self._source, target)

    def _finish(self, target: StepId) -> None:
        assert self._source is not None
        self._propose(self._source, target)
        if self.stack is not None:
            self.stack.pop()


class PanMode(ModeBase):
    """Hold space and drag, the way every canvas application does it.

    Qt's own ``ScrollHandDrag`` does the scrolling, so every hook here declines: the events
    fall through to the view, which pans instead of forwarding them to the scene. Leaving is
    what this mode is *for* — restoring the drag mode and the cursor is why it is an object.
    """

    name = PAN

    def __init__(self, deps: CanvasDeps) -> None:
        super().__init__(deps)
        self._was = QGraphicsView.DragMode.RubberBandDrag

    def enter(self) -> None:
        self._was = self.deps.view.dragMode()
        self.deps.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def exit(self) -> None:
        self.deps.view.setDragMode(self._was)


class RegionCreateMode(ModeBase):
    """Drag out the rectangle a new region covers. One region ends the mode; Esc leaves."""

    name = REGION_CREATE

    def __init__(self, deps: CanvasDeps) -> None:
        super().__init__(deps)
        self._anchor: QPointF | None = None

    def enter(self) -> None:
        self.deps.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.deps.status("Region: drag out the area it covers. Esc leaves.")

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.hide_outline()

    def mouse_press(self, event: CanvasEvent) -> bool:
        self._anchor = self._snapped(event.scene_pos)
        return True

    def mouse_move(self, event: CanvasEvent) -> bool:
        if self._anchor is not None:
            outline = QPainterPath()
            outline.addRoundedRect(
                QRectF(self._anchor, self._snapped(event.scene_pos)).normalized(),
                REGION_RADIUS,
                REGION_RADIUS,
            )
            self.deps.canvas.aim_outline(outline)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        if self._anchor is None:
            return True
        rect = QRectF(self._anchor, self._snapped(event.scene_pos)).normalized()
        self._anchor = None
        self.deps.canvas.hide_outline()
        if rect.width() >= MIN_REGION and rect.height() >= MIN_REGION:
            self.deps.canvas.region_create_requested.emit(
                rect.x(), rect.y(), rect.width(), rect.height()
            )
            if self.stack is not None:
                self.stack.pop()
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        return True  # No step-creating double clicks while drawing regions.

    def _snapped(self, point: QPointF) -> QPointF:
        snap = self.deps.canvas.snap
        return QPointF(snap(point.x()), snap(point.y()))


class RegionDragMode(ModeBase):
    """A region grabbed by its body: the frame moves, and so do the steps inside it.

    Which steps ride along is decided **at the press** — centres inside the rect — and held
    for the whole gesture, so a step half-carried out does not fall off mid-drag. Lives for
    one drag; a press that never moves is a click, and a click on a region selects it.
    """

    name = REGION_DRAG

    def __init__(self, deps: CanvasDeps, region: RegionItem, grab: QPointF) -> None:
        super().__init__(deps)
        self._region = region
        self._offset = grab - region.pos()
        self._start = region.pos()
        self._carried: dict[StepId, QPointF] = {}

    def enter(self) -> None:
        canvas = self.deps.canvas
        self._carried = {node.step_id: node.pos() for node in canvas.nodes_inside(self._region)}
        canvas.hold(self._region.region_id, set(self._carried))

    def exit(self) -> None:
        self.deps.canvas.release()

    def mouse_move(self, event: CanvasEvent) -> bool:
        self._region.setPos(event.scene_pos - self._offset)
        delta = self._region.pos() - self._start
        for step_id, was in self._carried.items():
            node = self.deps.canvas.node(step_id)
            if node is not None:
                node.setPos(was + delta)
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        canvas = self.deps.canvas
        at = self._region.pos()
        if at != self._start:
            carried = []
            for step_id in self._carried:
                node = canvas.node(step_id)
                if node is not None:
                    carried.append((step_id, node.pos().x(), node.pos().y()))
            canvas.regions_moved.emit([(self._region.region_id, at.x(), at.y())], carried)
        else:
            canvas.select_region(self._region.region_id)
        self._pop()
        return True

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            self._region.setPos(self._start)
            for step_id, was in self._carried.items():
                node = self.deps.canvas.node(step_id)
                if node is not None:
                    node.setPos(was)
            self._pop()
            return True
        return False

    def _pop(self) -> None:
        if self.stack is not None:
            self.stack.pop()


class RegionResizeMode(ModeBase):
    """A region grabbed by its corner grip. Lives for one resize; Esc puts it back."""

    name = REGION_RESIZE

    def __init__(self, deps: CanvasDeps, region: RegionItem) -> None:
        super().__init__(deps)
        self._region = region
        self._was = region.size()

    def enter(self) -> None:
        self.deps.canvas.hold(self._region.region_id, set())
        self.deps.view.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.release()

    def mouse_move(self, event: CanvasEvent) -> bool:
        snap = self.deps.canvas.snap
        local = event.scene_pos - self._region.pos()
        self._region.set_rect(max(MIN_REGION, snap(local.x())), max(MIN_REGION, snap(local.y())))
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        w, h = self._region.size()
        if (w, h) != self._was:
            at = self._region.pos()
            self.deps.canvas.region_resized.emit(self._region.region_id, at.x(), at.y(), w, h)
        self._pop()
        return True

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            self._region.set_rect(*self._was)
            self._pop()
            return True
        return False

    def _pop(self) -> None:
        if self.stack is not None:
            self.stack.pop()


class NodeResizeMode(ModeBase):
    """A card grabbed by an edge or a corner. Lives for one resize; Esc puts it back.

    The edge under the pointer is what moves and the opposite one stays put, so a card
    grows the way a window does — from the left, its seat moves with it. Each moved edge
    snaps while Snap to Grid is on, and no side goes below its minimum: the far edge is
    the limit, never the pointer. The card is held for the gesture, so a sync from the
    model — an agent's write, an undo — leaves its geometry alone until the release.
    """

    name = NODE_RESIZE

    def __init__(self, deps: CanvasDeps, node: StepNodeItem, edge: str) -> None:
        super().__init__(deps)
        self._node = node
        self._parts = edge.split("-")
        self._cursor = RESIZE_CURSORS[edge]
        self._was_pos = node.pos()
        self._was_size = node.size()
        self._seat = QRectF(node.pos(), QSizeF(*node.size()))

    def enter(self) -> None:
        self.deps.canvas.hold(None, {self._node.step_id})
        self.deps.view.viewport().setCursor(self._cursor)

    def exit(self) -> None:
        self.deps.view.viewport().unsetCursor()
        self.deps.canvas.release()

    def mouse_move(self, event: CanvasEvent) -> bool:
        snap = self.deps.canvas.snap
        rect = QRectF(self._seat)
        x, y = snap(event.scene_pos.x()), snap(event.scene_pos.y())
        if "left" in self._parts:
            rect.setLeft(min(x, rect.right() - MIN_NODE_W))
        elif "right" in self._parts:
            rect.setRight(max(x, rect.left() + MIN_NODE_W))
        if "top" in self._parts:
            rect.setTop(min(y, rect.bottom() - MIN_NODE_H))
        elif "bottom" in self._parts:
            rect.setBottom(max(y, rect.top() + MIN_NODE_H))
        self._node.set_size(rect.width(), rect.height())
        self._node.setPos(rect.topLeft())
        return True

    def mouse_release(self, event: CanvasEvent) -> bool:
        at, (w, h) = self._node.pos(), self._node.size()
        if at != self._was_pos or (w, h) != self._was_size:
            self.deps.canvas.node_resized.emit(self._node.step_id, at.x(), at.y(), w, h)
        self._pop()
        return True

    def key_press(self, key: CanvasKey) -> bool:
        if key.key == Qt.Key.Key_Escape:
            self._node.set_size(*self._was_size)
            self._node.setPos(self._was_pos)
            self._pop()
            return True
        return False

    def _pop(self) -> None:
        if self.stack is not None:
            self.stack.pop()


class LassoMode(ModeBase):
    """Draw round the steps to pick: every card the outline touches is selected.

    A rubber band is a box, and a cluster on a busy canvas rarely is. One lasso ends the
    mode, like one link ends connect; Shift held on the release adds the catch to what was
    already selected rather than replacing it. A press that never moves is a click, and a
    click here means nothing — the selection is left as it was.
    """

    name = LASSO

    def __init__(self, deps: CanvasDeps) -> None:
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


class IdleMode(ModeBase):
    """The base. Qt does selection, rubber banding and node dragging; this catches the rest:
    a press on a card's link handle, on its frame, or on a region's body or grip."""

    name = IDLE

    def mouse_press(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.node_at(event.scene_pos)
        if node is not None and node.is_over_handle(event.scene_pos):
            # Claimed before Qt sees it, so the press starts neither a move nor a rubber band.
            if self.stack is not None:
                self.stack.push(LinkDragMode(self.deps, node.step_id))
            return True
        if node is not None:
            edge = node.edge_at(event.scene_pos)
            if edge and event.button == Qt.MouseButton.LeftButton and self.stack is not None:
                self.stack.push(NodeResizeMode(self.deps, node, edge))
                return True
            return False
        region = self.deps.canvas.region_at(event.scene_pos)
        if region is not None and self.stack is not None:
            # A region's body is invisible to Qt's hit-testing (see RegionItem.shape), so
            # these two gestures are claimed here; the title strip and border fall through
            # to Qt, which selects and moves the frame alone.
            if region.is_over_grip(event.scene_pos):
                self.stack.push(RegionResizeMode(self.deps, region))
                return True
            if region.is_over_body(event.scene_pos):
                self.stack.push(RegionDragMode(self.deps, region, event.scene_pos))
                return True
        return False

    def mouse_move(self, event: CanvasEvent) -> bool:
        """Cursor feedback only — the event still falls through to Qt, which hovers and
        drags. A card's frame shows the resize arrows so the gesture can be found; the
        handle wins its corner of the right edge, as it does on the press."""
        if event.buttons == Qt.MouseButton.NoButton:
            node = self.deps.canvas.node_at(event.scene_pos)
            edge = ""
            if node is not None and not node.is_over_handle(event.scene_pos):
                edge = node.edge_at(event.scene_pos)
            viewport = self.deps.view.viewport()
            if edge:
                if viewport.cursor().shape() != RESIZE_CURSORS[edge]:
                    viewport.setCursor(RESIZE_CURSORS[edge])
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
        region = self.deps.canvas.region_at(event.scene_pos)
        if region is not None and region.is_over_title(event.scene_pos):
            self.deps.canvas.select_region(region.region_id)
            self.deps.run_action("regions.rename")
            return True
        point = event.scene_pos
        self.deps.canvas.create_requested.emit(*centred_on(point.x(), point.y()))
        return True
