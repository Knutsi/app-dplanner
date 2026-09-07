"""An in-tab action toolbar: one button per action id, restated on every context change.

The registry stays the single source of truth — this presenter renders a chosen subset of
specs as buttons, exactly as the menu bar renders all of them as QActions. Shortcuts stay
with the menu bar's QActions; a click here goes through ``registry.run``, so the state
gate holds even if a stale context left a button enabled. Toolbars live inside tabs, so
unlike the app-lifetime menu bar they must be ``dispose()``d when their tab closes.

**It renders the application's action state, not its own tab's.** A toolbar in a background
tab — or in a tab group the user is not in — shows what the *active* surface can do, because
there is one ``ContextService``. Invisible while only one tab is on screen; visible once the
window is split. If that ever matters, the fix is a ``set_active(bool)`` that greys the row
when its group is not the active one, not a context per group.

**A button may drop its verb's submenu down.** ``menus`` names, per action id, the
``(menu, submenu)`` whose entries belong under that button's arrow: the button runs its own
verb on a click and renders that child menu on the arrow — through ``fill_menu``, so it is
the menu, never a copy of it, and it is refilled on every open against the context and the
palette of that moment.

:func:`control_bar` is the other strip a tab page carries: a row of *its own* controls — a
selector, a toggle, a spin box — that overflows into a » menu when the width is short.
"""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QToolBar, QToolButton, QWidget

from dplanner.framework.action_menu import fill_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService
from dplanner.theme.icons import ICON_SIZE

CONTROL_GAP = 8


def control_bar(parent: QWidget | None = None) -> QToolBar:
    """A strip of controls on a tab page, not application chrome.

    A ``QToolBar`` rather than a row of widgets because it is the one widget in Qt that
    degrades a full control row gracefully: too narrow for its contents it grows the »
    overflow button and puts the tail in a menu, where a plain row simply overlaps. The
    ``#ControlBar`` rule in ``theme.qss`` takes its frame and ground away. A widget added
    to it is wrapped in an action, and it is the *action* that carries visibility — hold
    what ``addWidget`` returns when a control comes and goes.
    """
    bar = QToolBar(parent)
    bar.setObjectName("ControlBar")
    bar.setMovable(False)
    bar.setFloatable(False)
    bar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    inner = bar.layout()
    if inner is not None:
        inner.setSpacing(CONTROL_GAP)
        inner.setContentsMargins(0, 0, 0, 0)
    return bar


class ActionToolbar(QWidget):
    def __init__(
        self,
        registry: ActionRegistry,
        context: ContextService,
        action_ids: Sequence[str],
        button_text: Mapping[str, str] | None = None,
        parent: QWidget | None = None,
        menus: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActionToolbar")
        self._registry = registry
        self._context = context
        # Per-action face override (glyphs, short forms); the spec label becomes the
        # tooltip fallback so no meaning is lost on a compact button.
        self._button_text = dict(button_text or {})
        # Action id → the (menu, submenu) that button drops down.
        self._menus = dict(menus or {})
        self._buttons: dict[str, QToolButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for action_id in action_ids:
            button = QToolButton(self)
            button.setObjectName("ToolbarButton")
            # A toolbar never takes the keyboard. Without this, clicking a button moves focus
            # off the surface the button just acted on, and the next keystroke goes nowhere —
            # which a canvas with its own key bindings notices immediately.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # And it keeps its face: a layout short of room shrinks widgets to their minimum,
            # and a 10 px wide button with a 16 px glyph in it shows neither icon nor label.
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, a=action_id: registry.run(a, context.current())
            )
            if action_id in self._menus:
                self._attach_menu(button, *self._menus[action_id])
            layout.addWidget(button)
            self._buttons[action_id] = button

        self._unsubscribe = context.changed.connect(self._refresh)
        self._refresh(context.current())

    def _attach_menu(self, button: QToolButton, menu: str, submenu: str) -> None:
        """The arrow beside a button, rendering one child menu of the action table.

        ``MenuButtonPopup``, not ``InstantPopup``: the button half still runs the verb, so
        New makes a plain step in one click and the arrow is only for the other kinds. The
        popup is refilled on every open — a verb's state, its label and the theme's ink can
        all have changed since the last one.

        Two targets in one button means the arrow has to *be* one: Qt sizes it from
        ``PM_MenuButtonIndicator`` — about ten pixels — which is both unaimable and reads
        as a rendering fault. ``hasMenu`` is what lets the theme widen it and leave the
        words room; the hairline down its left edge is what says the halves differ.
        """
        popup = QMenu(button)
        popup.aboutToShow.connect(lambda: self._refill(popup, menu, submenu))
        button.setMenu(popup)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        # The theme widens the arrow into a target and steps the words aside for it; a
        # styled subcontrol is outside Qt's size hint, so the room has to be asked for.
        button.setProperty("hasMenu", True)

    def _refill(self, popup: QMenu, menu: str, submenu: str) -> None:
        popup.clear()
        fill_menu(popup, self._registry, self._context, menu, submenu)

    def menu_for(self, action_id: str) -> QMenu | None:
        """The dropdown a button carries, filled as it would open — a test's way in."""
        button = self._buttons.get(action_id)
        popup = button.menu() if button is not None else None
        if popup is None or action_id not in self._menus:
            return None
        self._refill(popup, *self._menus[action_id])
        return popup

    def set_button_icons(self, icons: Mapping[str, QIcon]) -> None:
        """Painted icons per action id; with an empty text override the button renders
        icon-only (the spec label survives as the tooltip). Re-call on theme changes."""
        for action_id, icon in icons.items():
            button = self._buttons.get(action_id)
            if button is not None:
                button.setIcon(icon)

    def _refresh(self, context: Context) -> None:
        for action_id, button in self._buttons.items():
            spec = self._registry.spec(action_id)
            state = spec.state(context)
            label = state.label if state.label is not None else spec.label
            text = self._button_text.get(action_id, label.replace("&", ""))
            button.setText(text)
            # QToolButton shows its icon and nothing else unless told otherwise, so a button
            # with words on it has to say so — and one with an empty override stays a glyph.
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if text
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            button.setVisible(state.visible)
            button.setEnabled(state.enabled)
            if state.checked is not None:
                button.setCheckable(True)
                button.setChecked(state.checked)
            button.setToolTip(spec.tip or label.replace("&", ""))

    def dispose(self) -> None:
        self._unsubscribe()
