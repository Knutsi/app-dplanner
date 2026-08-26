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
- **A mode asks the model.** Whether a link is legal is ``Product.link_refusal`` under the
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

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsView

from dplanner.core.signals import Signal
from dplanner.domain.model import StepId
from dplanner.modules.project_editor.items import NODE_H, NODE_W, StepNodeItem
from dplanner.modules.project_editor.selection import CanvasSelection

# How the current mode reaches the context, so an action's ``state`` can read it as a pure
# function — which is what makes the Connect toolbar button check itself for free.
MODE_URI_PREFIX = "app://canvas-mode/"

IDLE = "idle"
CONNECT = "connect"
PAN = "pan"
LINK_DRAG = "link-drag"


def mode_uri(name: str) -> str:
    return f"{MODE_URI_PREFIX}{name}"


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

    def node_at(self, scene_pos: QPointF) -> StepNodeItem | None: ...

    def node(self, step_id: StepId) -> StepNodeItem | None: ...

    def select_step(self, step_id: StepId | None) -> None: ...

    def selected_step(self) -> StepId | None: ...

    def link_refusal(self, waiter: StepId, source: StepId) -> str | None: ...

    def aim_preview(self, origin: QPointF, cursor: QPointF, ok: bool) -> None: ...

    def hide_preview(self) -> None: ...

    def set_link_states(self, valid: StepId | None, invalid: StepId | None) -> None: ...


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


class CanvasMode(Protocol):
    name: str

    def enter(self) -> None: ...

    def exit(self) -> None: ...

    def mouse_press(self, event: CanvasEvent) -> bool: ...

    def mouse_move(self, event: CanvasEvent) -> bool: ...

    def mouse_release(self, event: CanvasEvent) -> bool: ...

    def double_click(self, event: CanvasEvent) -> bool: ...

    def key_press(self, key: CanvasKey) -> bool: ...

    def key_release(self, key: CanvasKey) -> bool: ...


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


class IdleMode(ModeBase):
    """The base. Qt does selection, rubber banding and node dragging; this catches the rest."""

    name = IDLE

    def mouse_press(self, event: CanvasEvent) -> bool:
        node = self.deps.canvas.node_at(event.scene_pos)
        if node is None or not node.is_over_handle(event.scene_pos):
            return False
        # Claimed before Qt sees it, so the press starts neither a move nor a rubber band.
        if self.stack is not None:
            self.stack.push(LinkDragMode(self.deps, node.step_id))
        return True

    def double_click(self, event: CanvasEvent) -> bool:
        if self.deps.canvas.node_at(event.scene_pos) is not None:
            return False
        point = event.scene_pos
        self.deps.canvas.create_requested.emit(point.x() - NODE_W / 2, point.y() - NODE_H / 2)
        return True
