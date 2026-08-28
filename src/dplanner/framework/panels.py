"""Where a module's panel goes: the window's left, right and bottom areas.

A **panel** is a surface anchored beside the tabs rather than inside one — the index tree, a
detail editor, an output log. A module registers a :class:`PanelSpec` saying what it is called
and where it would like to sit; the window's :class:`PanelDock` builds it once and puts it in an
area. The user moves it between areas from its header's right-click menu, hides it from
*View ▸ Panels*, and can collapse a whole side at once (*View ▸ Left/Right Side Panel*,
Ctrl+B / Ctrl+Alt+B) — all of it remembered.

**One panel, not one per tab.** This is the whole reason the dock exists. A panel built inside
an activity is duplicated the moment the window is split, and two copies of one editor is not a
richer window — it is the same width spent twice. So a panel lives at the window and follows
what the user is doing.

**It follows by reading the context, not by being told.** A panel that cares implements
:class:`ContextPanel`; the dock calls ``show_context`` on every context change and hides the
panel when it answers False. Nothing pushes at a panel and no panel subscribes to the context
itself — there is one subscription here, and *"only the active pane speaks for the user"*
(see ``ProjectActivity._is_active``) is then all it takes for the panel to follow the focused
pane, because that rule already decides who may publish a selection.

**Areas, not draggable docks.** Three fixed places and a menu to choose between them. Qt's
``QDockWidget`` gives floating windows, tear-off drags and a serialized layout blob nobody can
read; what this needs is "put that over there", which is a right-click.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QMenu, QSplitter, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.context import Context, ContextService


class PanelArea(StrEnum):
    """The three places a panel can be anchored. A ``StrEnum`` so it stores as itself."""

    LEFT = "left"
    RIGHT = "right"
    BOTTOM = "bottom"


# Logical pixels — Qt 6 scales them per monitor, so a stored value stays meaningful across DPI
# changes. The clamp keeps a stale or corrupt one from leaving an area invisible or
# window-filling. The defaults are the sidebar's and the detail panel's historical widths.
AREA_DEFAULT_SIZE = {PanelArea.LEFT: 275, PanelArea.RIGHT: 360, PanelArea.BOTTOM: 220}
AREA_MIN_SIZE = 120
AREA_MAX_SIZE = 600

# DESIGN.md's side-panel spacing: 16 px outer margins, 6 px from a caption to what it labels.
HEADER_MARGIN = 16
HEADER_TOP = 12
HEADER_GAP = 6

_AREA_OBJECT_NAMES = {
    PanelArea.LEFT: "PanelAreaLeft",
    PanelArea.RIGHT: "PanelAreaRight",
    PanelArea.BOTTOM: "PanelAreaBottom",
}


@runtime_checkable
class ContextPanel(Protocol):
    """A panel whose content follows what the user is doing.

    Implement this and the dock keeps the panel pointed at the current context; leave it out
    and the panel is simply always on screen (the index tree).
    """

    def show_context(self, context: Context) -> bool:
        """Retarget to this context, and say whether there is anything to show.

        False takes the panel off screen until there is — which is how two panels can share
        one area and be mutually exclusive without either knowing the other exists.
        """
        ...

    def dispose(self) -> None:
        """Disconnect from the model. Called when the window goes."""
        ...


@dataclass(frozen=True)
class PanelSpec:
    id: str  # Module-prefixed, globally unique.
    title: str  # The header strip's text, and the View ▸ Panels entry.
    factory: Callable[[], QWidget]  # Built once, when the dock installs it.
    area: PanelArea = PanelArea.RIGHT  # Where it goes until the user says otherwise.
    order: int = 50  # Position within its area; lowest first.


class PanelRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, PanelSpec] = {}
        # The dock exists before any module registers, so late arrivals have to reach it —
        # the same arrangement as IndexSegmentRegistry.
        self.registered: Signal[PanelSpec] = Signal()

    def register(self, spec: PanelSpec) -> None:
        if spec.id in self._panels:
            raise ValueError(f"panel {spec.id!r} already registered")
        self._panels[spec.id] = spec
        self.registered.emit(spec)

    def panels(self) -> list[PanelSpec]:
        return sorted(self._panels.values(), key=lambda p: (p.order, p.id))


def _stored_size(area: PanelArea) -> int:
    raw = QSettings().value(f"layout/areas/{area.value}", AREA_DEFAULT_SIZE[area])
    try:
        saved = int(raw) if isinstance(raw, int | float | str) else AREA_DEFAULT_SIZE[area]
    except ValueError:
        saved = AREA_DEFAULT_SIZE[area]
    return max(AREA_MIN_SIZE, min(AREA_MAX_SIZE, saved))


def _store_size(area: PanelArea, size: int) -> None:
    QSettings().setValue(f"layout/areas/{area.value}", size)


def _stored_collapsed(area: PanelArea) -> bool:
    raw = QSettings().value(f"layout/areas/{area.value}/collapsed", False)
    return raw in (True, "true", "True", 1, "1")


def _store_collapsed(area: PanelArea, collapsed: bool) -> None:
    QSettings().setValue(f"layout/areas/{area.value}/collapsed", collapsed)


class _PanelFrame(QWidget):
    """One panel on screen: its header strip, and the module's widget below it.

    The header is what makes a panel a thing you can point at — it names the panel, separates
    it from whatever is stacked beside it, and carries the right-click menu. The content
    widget keeps its own context menu; a right-click that lands on the header (or on the
    frame's own margins) propagates here instead.
    """

    def __init__(self, spec: PanelSpec, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelFrame")
        self.spec = spec
        self.content = content
        # Whether the panel's own contract says it has something to show. Combined with the
        # user's hide in PanelDock._refresh.
        self.has_content = True

        self.header = QLabel(spec.title, self)
        self.header.setObjectName("InspectorCaption")
        self.header.setContentsMargins(HEADER_MARGIN, HEADER_TOP, HEADER_MARGIN, HEADER_GAP)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(content, 1)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)


class PanelDock(QSplitter):
    """The window's centre and the three areas around it.

    The dock *is* the horizontal splitter rather than holding one, so its own width is the
    width the areas are sized against — there is no layout pass in between that can leave the
    two disagreeing while the window is still being built.
    """

    def __init__(
        self,
        panels: PanelRegistry,
        context: ContextService,
        centre: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("PanelDock")
        self.setChildrenCollapsible(False)
        self._frames: dict[str, _PanelFrame] = {}
        self._areas_of: dict[str, PanelArea] = {}
        self._hidden: set[str] = set()
        self._collapsed: set[PanelArea] = {a for a in PanelArea if _stored_collapsed(a)}
        # Read once and updated on every drag. Kept in memory because the sizes are
        # re-applied on each resize, and QSettings is not free per mouse move.
        self._sizes = {area: _stored_size(area) for area in PanelArea}

        # A panel was shown, hidden or moved. What View ▸ Panels re-reads its checkmarks from.
        self.panels_changed: Signal[str] = Signal()
        # A whole area was collapsed or expanded. What the side-panel toggles re-read theirs
        # from — a separate signal because panels_changed carries a panel id.
        self.areas_changed: Signal[PanelArea] = Signal()

        self._middle = QSplitter(Qt.Orientation.Vertical, self)
        self._middle.setChildrenCollapsible(False)
        self._middle.addWidget(centre)

        self._areas: dict[PanelArea, QSplitter] = {}
        for area in (PanelArea.LEFT, PanelArea.RIGHT, PanelArea.BOTTOM):
            orientation = (
                Qt.Orientation.Horizontal if area is PanelArea.BOTTOM else Qt.Orientation.Vertical
            )
            splitter = QSplitter(orientation, self)
            splitter.setObjectName(_AREA_OBJECT_NAMES[area])
            splitter.hide()
            self._areas[area] = splitter
        self.addWidget(self._areas[PanelArea.LEFT])
        self.addWidget(self._middle)
        self.addWidget(self._areas[PanelArea.RIGHT])
        self._middle.addWidget(self._areas[PanelArea.BOTTOM])
        # Only the centre grows: a wider window is a wider canvas, and a panel the user
        # sized to 360 px stays 360 px.
        self.setStretchFactor(1, 1)
        self._middle.setStretchFactor(0, 1)

        self.splitterMoved.connect(self._persist_outer)
        self._middle.splitterMoved.connect(self._persist_middle)

        self._context = context
        for spec in panels.panels():
            self._install(spec)
        panels.registered.connect(self._install)
        self._unsubscribe = context.changed.connect(self._on_context)

    # -- what a module's panel is doing --------------------------------------------------------

    def widget_for(self, panel_id: str) -> QWidget | None:
        frame = self._frames.get(panel_id)
        return None if frame is None else frame.content

    def area_of(self, panel_id: str) -> PanelArea | None:
        return self._areas_of.get(panel_id)

    def is_panel_visible(self, panel_id: str) -> bool:
        """Whether the user has this panel switched on — not whether it is on screen.

        A panel with nothing to say is off screen while still being "visible" in this sense,
        and that is the distinction the View menu's checkmark means.
        """
        return panel_id in self._frames and panel_id not in self._hidden

    def is_panel_showing(self, panel_id: str) -> bool:
        """Whether the panel is on screen: switched on, and with something to show."""
        frame = self._frames.get(panel_id)
        return frame is not None and not frame.isHidden()

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        if panel_id not in self._frames:
            return
        if visible:
            self._hidden.discard(panel_id)
            # Switching a panel on is a gesture that puts it somewhere — a checkmark that
            # turns on with nothing appearing reads as a bug, so the collapsed side opens.
            self.set_area_collapsed(self._areas_of[panel_id], False)
        else:
            self._hidden.add(panel_id)
        QSettings().setValue(f"layout/panels/{panel_id}/hidden", not visible)
        self._refresh()
        self.panels_changed.emit(panel_id)

    def move_panel(self, panel_id: str, area: PanelArea) -> None:
        frame = self._frames.get(panel_id)
        if frame is None or self._areas_of.get(panel_id) is area:
            return
        self._areas_of[panel_id] = area
        QSettings().setValue(f"layout/panels/{panel_id}/area", area.value)
        self._place(frame)
        # "Put that over there" means over there, visibly — not into a collapsed side.
        self.set_area_collapsed(area, False)
        self._refresh()
        self.panels_changed.emit(panel_id)

    def is_area_collapsed(self, area: PanelArea) -> bool:
        """Whether the user has this whole side folded away, panels' own state untouched."""
        return area in self._collapsed

    def set_area_collapsed(self, area: PanelArea, collapsed: bool) -> None:
        if collapsed == (area in self._collapsed):
            return
        if collapsed:
            self._collapsed.add(area)
        else:
            self._collapsed.discard(area)
        _store_collapsed(area, collapsed)
        self._refresh()
        self.areas_changed.emit(area)

    def dispose(self) -> None:
        """Detach from the context and from the model. Idempotent — a workspace switch
        closes the window, and the suite closes it again."""
        self._unsubscribe()
        for frame in self._frames.values():
            if isinstance(frame.content, ContextPanel):
                frame.content.dispose()

    # -- installing ------------------------------------------------------------------------------

    def _install(self, spec: PanelSpec) -> None:
        # No duplicate check: the registry refuses a repeated id, so one id is one frame.
        frame = _PanelFrame(spec, spec.factory(), self)
        frame.customContextMenuRequested.connect(
            lambda position, panel_id=spec.id: self._show_menu(panel_id, position)
        )
        self._frames[spec.id] = frame
        self._areas_of[spec.id] = self._stored_area(spec)
        if self._stored_hidden(spec.id):
            self._hidden.add(spec.id)
        if isinstance(frame.content, ContextPanel):
            frame.has_content = frame.content.show_context(self._context.current())
        self._place(frame)
        self._refresh()

    def _stored_area(self, spec: PanelSpec) -> PanelArea:
        raw = QSettings().value(f"layout/panels/{spec.id}/area")
        try:
            return PanelArea(raw) if isinstance(raw, str) else spec.area
        except ValueError:
            return spec.area  # A build that no longer has that area.

    def _stored_hidden(self, panel_id: str) -> bool:
        raw = QSettings().value(f"layout/panels/{panel_id}/hidden", False)
        return raw in (True, "true", "True", 1, "1")

    def _place(self, frame: _PanelFrame) -> None:
        """Put a frame in its area, in ``(order, id)`` sequence among whatever is there."""
        area = self._areas[self._areas_of[frame.spec.id]]
        key = (frame.spec.order, frame.spec.id)
        siblings = [
            f
            for f in self._frames.values()
            if f is not frame and self._areas_of[f.spec.id] is self._areas_of[frame.spec.id]
        ]
        index = len([f for f in siblings if (f.spec.order, f.spec.id) <= key])
        area.insertWidget(index, frame)

    # -- what is on screen -----------------------------------------------------------------------

    def _on_context(self, context: Context) -> None:
        changed = False
        for frame in self._frames.values():
            if isinstance(frame.content, ContextPanel):
                has_content = frame.content.show_context(context)
                if has_content != frame.has_content:
                    frame.has_content = has_content
                    changed = True
        if changed:
            self._refresh()

    def _refresh(self) -> None:
        # isHidden() rather than isVisible() throughout: a widget whose window has not been
        # shown yet is not visible however it was set, and the dock is built and filled
        # before anything is on screen.
        for panel_id, frame in self._frames.items():
            # Collapse is tested on the frame, not just the area splitter: a frame under a
            # hidden parent still answers isHidden() == False, and is_panel_showing reads it.
            frame.setVisible(
                frame.has_content
                and panel_id not in self._hidden
                and self._areas_of[panel_id] not in self._collapsed
            )
        for area, splitter in self._areas.items():
            # An area with nothing in it takes no space at all — an empty right side is not a
            # blank column, it is a wider canvas.
            splitter.setVisible(any(not f.isHidden() for f in self._frames_in(area)))
        self._apply_sizes()

    def _frames_in(self, area: PanelArea) -> list[_PanelFrame]:
        return [f for f in self._frames.values() if self._areas_of[f.spec.id] is area]

    def _size_for(self, area: PanelArea) -> int:
        return 0 if self._areas[area].isHidden() else self._sizes[area]

    def _apply_sizes(self) -> None:
        left, right = self._size_for(PanelArea.LEFT), self._size_for(PanelArea.RIGHT)
        self.setSizes([left, max(1, self.width() - left - right), right])
        bottom = self._size_for(PanelArea.BOTTOM)
        self._middle.setSizes([max(1, self._middle.height() - bottom), bottom])

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        # The dock is filled before the window is on screen, so the first honest width
        # arrives here. Re-applying is safe at any time: what it applies is the size the user
        # last dragged to, and a window resize should give the difference to the tabs.
        super().resizeEvent(event)
        self._apply_sizes()

    def _persist_outer(self, _position: int, _index: int) -> None:
        sizes = self.sizes()
        for area, size in ((PanelArea.LEFT, sizes[0]), (PanelArea.RIGHT, sizes[2])):
            # 0 means the area was dragged shut — restoring that next time would look like a
            # panel that had gone missing, so only real sizes are remembered. The isHidden()
            # guard also keeps a collapsed area from overwriting its remembered width.
            if not self._areas[area].isHidden() and size > 0:
                self._sizes[area] = size
                _store_size(area, size)

    def _persist_middle(self, _position: int, _index: int) -> None:
        size = self._middle.sizes()[1]
        if not self._areas[PanelArea.BOTTOM].isHidden() and size > 0:
            self._sizes[PanelArea.BOTTOM] = size
            _store_size(PanelArea.BOTTOM, size)

    # -- the header's menu -------------------------------------------------------------------------

    def _panel_menu(self, panel_id: str) -> QMenu:
        """ "Put that over there" — the whole of what moving a panel is.

        Built rather than exec'd here so it can be read in a test without a modal loop.
        """
        current = self._areas_of[panel_id]
        menu = QMenu(self)
        for area, label in (
            (PanelArea.LEFT, "Move to &Left"),
            (PanelArea.RIGHT, "Move to &Right"),
            (PanelArea.BOTTOM, "Move to &Bottom"),
        ):
            entry = menu.addAction(label)
            entry.setCheckable(True)
            entry.setChecked(area is current)
            entry.setEnabled(area is not current)
            entry.triggered.connect(
                lambda _checked=False, target=area: self.move_panel(panel_id, target)
            )
        menu.addSeparator()
        hide = menu.addAction("&Hide Panel")
        hide.triggered.connect(lambda _checked=False: self.set_panel_visible(panel_id, False))
        return menu

    def _show_menu(self, panel_id: str, position: QPoint) -> None:
        frame = self._frames[panel_id]
        self._panel_menu(panel_id).exec(frame.mapToGlobal(position))
