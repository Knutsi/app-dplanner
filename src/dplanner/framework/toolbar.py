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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPalette,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.framework.action_menu import fill_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService
from dplanner.theme.icons import FILTER_ICON_W, ICON_SIZE, close_icon, filter_icon
from dplanner.theme.tokens import CONTROL_GAP, CONTROL_HEIGHT, DENSE_GAP, SECONDARY_ALPHA


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


MORE = "…"
DIVIDER_INSET = 6  # A divider stops this far short of the controls' top and bottom.


@dataclass
class _Item:
    widget: QWidget
    action: QAction | None  # A verb's action, which the … menu lists; None for a widget.
    divider: bool = False


class Toolbar(QWidget):
    """A strip of verbs as glyphs with their words in tooltips, overflowing into a … menu.

    DESIGN.md's *Toolbars*. A verb is a glyph (``theme/icons.py``'s painters, inked in the
    secondary tone and re-inked on a palette change) whose words and shortcut live in the
    tooltip; a widget (a filter) sits among them; a divider parts groups. What no longer
    fits is taken off the strip from the right and listed, as glyph *and* words, in a
    ``…`` menu at the strip's end — never a second row, and never Qt's own overflow,
    which pops the hidden buttons up as glyphs again. A widget never enters the menu; it
    hides when there is no room for it. Every control is one height (the stylesheet's).

    The strip's size hint is the … button's, so a page can be dragged narrower than its
    verbs and the strip answers by folding rather than by squeezing.

    ``dense`` packs a strip whose glyphs are read as **one set** rather than aimed at one
    at a time — the step panel's aspect bar, where the row answers "what does this step
    carry". A verb strip folds gracefully because losing a verb to the … menu costs a
    click; a set that folds stops answering its question at all, and the aspect bar in a
    360 px dock showed two of its ten toggles at the verb strip's metrics. Dense keeps
    `CONTROL_HEIGHT` and takes the width back from the sides and the gaps.
    """

    def __init__(self, parent: QWidget | None = None, *, dense: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("ControlBar")
        self.setProperty("dense", dense)  # `#ControlBar[dense="true"]` narrows the buttons.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._items: list[_Item] = []
        self._painters: dict[QAction, Callable[[QColor], QIcon]] = {}
        self._tips: dict[QAction, str] = {}
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(DENSE_GAP if dense else CONTROL_GAP)
        self._more = QToolButton(self)
        self._more.setObjectName("ToolbarButton")
        self._more.setText(MORE)
        self._more.setToolTip("More")
        self._more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more.setFixedHeight(CONTROL_HEIGHT)
        self._menu = QMenu(self._more)
        self._menu.aboutToShow.connect(self._fill_more)
        self._more.setMenu(self._menu)
        self._more.hide()
        self._layout.addWidget(self._more)
        self._layout.addStretch(1)

    # -- filling it --------------------------------------------------------------------

    def add_verb(
        self,
        text: str,
        icon: Callable[[QColor], QIcon],
        slot: Callable[[], object],
        *,
        shortcut: str = "",
        checkable: bool = False,
        tip: str = "",
    ) -> QAction:
        """A glyph on the strip; ``text`` (and the shortcut) is its tooltip and its words in
        the … menu. The returned action is what a host enables, checks and rewords.

        ``tip`` is for a verb that has more to say than its words — a registered
        ``ActionSpec.tip``, say. It stands in the tooltip while the words still name the
        entry in the … menu, so a host that rewords an action to carry a refusal does not
        lose the standing explanation with it.
        """
        action = QAction(text, self)
        action.setCheckable(checkable)
        if tip:
            self._tips[action] = tip
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False: slot())
        action.changed.connect(lambda a=action: self._retip(a))
        self._painters[action] = icon
        self._retip(action)
        button = QToolButton(self)
        button.setObjectName("ToolbarButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))  # Qt's toolbar default is 24.
        button.setDefaultAction(action)
        self._place(_Item(button, action))
        self._reink()
        return action

    def add_widget(self, widget: QWidget) -> QWidget:
        """A control that is not a verb — a filter, a grouping — among the verbs."""
        widget.setParent(self)
        self._place(_Item(widget, None))
        return widget

    def add_divider(self) -> None:
        rule = QFrame(self)
        rule.setObjectName("ToolbarDivider")
        rule.setFixedSize(1, CONTROL_HEIGHT - 2 * DIVIDER_INSET)
        self._place(_Item(rule, None, divider=True))

    def _place(self, item: _Item) -> None:
        if not item.divider:
            # One height for every control, in code: the styles' content heights agree for
            # a worded button and a combo and disagree by three pixels for one with a menu.
            item.widget.setFixedHeight(CONTROL_HEIGHT)
        self._layout.insertWidget(
            self._layout.indexOf(self._more), item.widget, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self._items.append(item)
        self._reflow()

    def verbs(self) -> list[QAction]:
        return [item.action for item in self._items if item.action is not None]

    # -- the words -----------------------------------------------------------------------

    def _retip(self, action: QAction) -> None:
        words = self._tips.get(action) or action.text()
        if not action.shortcut().isEmpty():
            words = f"{words}  {action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)}"
        if action.toolTip() != words:
            action.setToolTip(words)

    def _reink(self) -> None:
        ink = self.palette().color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        for action, painter in self._painters.items():
            action.setIcon(painter(ink))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._reink()  # A glyph carries the ink it was painted in.
        super().changeEvent(event)

    # -- overflow ------------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._more.sizeHint().width(), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.sizeHint()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._reflow()

    def hidden_items(self) -> list[_Item]:
        return [item for item in self._items if item.widget.isHidden()]

    def _reflow(self) -> None:
        """Show what fits from the left; fold the rest into the … menu."""
        gap = self._layout.spacing()
        widths = [item.widget.sizeHint().width() for item in self._items]
        room = self.width()
        shown = len(self._items)
        if sum(widths) + gap * max(0, len(widths) - 1) > room:
            room -= self._more.sizeHint().width() + gap
            used = 0
            shown = 0
            for width in widths:
                if used + width > room:
                    break
                used += width + gap
                shown += 1
        # A divider at either end of what is shown parts nothing.
        while shown and self._items[shown - 1].divider:
            shown -= 1
        for position, item in enumerate(self._items):
            visible = position < shown and not (position == 0 and item.divider)
            item.widget.setVisible(visible)
        self._more.setVisible(shown < len(self._items))

    def _fill_more(self) -> None:
        self._menu.clear()
        pending_divider = False
        for item in self._items:
            if not item.widget.isHidden():
                continue
            if item.divider:
                pending_divider = bool(self._menu.actions())
                continue
            if item.action is None:
                continue  # A widget never enters the menu.
            if pending_divider:
                self._menu.addSeparator()
                pending_divider = False
            self._menu.addAction(item.action)


class _StayOpenMenu(QMenu):
    """A menu of checkable entries that stays open while they are toggled, so several
    filters can be picked in one visit; anything else closes it as a menu does."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class FilterButton(QWidget):
    """``[funnel] Filter`` with a clear button beside it: the filters in a popup, an
    indicator while any is on, and a second button that clears them.

    DESIGN.md's *Toolbars*. The face drops a menu of checkable filters down and stays the
    same size whatever is on: the indicator is the glyph itself — an outline funnel, or a
    filled one with a dot in the slot before it — and the accent washes the face's ground
    and colours its border and glyph, so the words stay legible and the state reads as a
    filter being on, not a mode being pressed. The clear button beside it is greyed until
    a filter is on, never hidden. ``changed`` says when the set of active filters changed.
    """

    def __init__(self, parent: QWidget | None = None, *, label: str = "Filter") -> None:
        super().__init__(parent)
        self.changed: Signal[()] = Signal("filter.changed")
        self._label = label
        self._actions: dict[str, QAction] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.face = QToolButton(self)
        self.face.setObjectName("FilterButtonFace")
        self.face.setText(label)
        self.face.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.face.setIconSize(QSize(FILTER_ICON_W, ICON_SIZE))  # The dot's slot is in it.
        self.face.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.face.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.face.setFixedHeight(CONTROL_HEIGHT)
        self.menu = _StayOpenMenu(self.face)
        self.face.setMenu(self.menu)
        row.addWidget(self.face)
        self.clear_button = QToolButton(self)
        self.clear_button.setObjectName("FilterButtonClear")
        self.clear_button.setToolTip("Clear the filters")
        self.clear_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.setFixedHeight(CONTROL_HEIGHT)
        self.clear_button.clicked.connect(lambda _checked=False: self.clear())
        row.addWidget(self.clear_button)
        self._show_state()

    def add_filter(self, key: str, text: str) -> QAction:
        """One checkable entry in the popup, known to the host by ``key``."""
        action = QAction(text, self.menu)
        action.setCheckable(True)
        action.toggled.connect(lambda _on: self._show_state(announce=True))
        self.menu.addAction(action)
        self._actions[key] = action
        return action

    def active(self) -> list[str]:
        return [key for key, action in self._actions.items() if action.isChecked()]

    def set_active(self, keys: set[str] | list[str]) -> None:
        wanted = set(keys)
        for key, action in self._actions.items():
            action.blockSignals(True)
            action.setChecked(key in wanted)
            action.blockSignals(False)
        self._show_state(announce=True)

    def clear(self) -> None:
        self.set_active(set())

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._show_state()  # The glyphs carry the ink they were painted in.
        super().changeEvent(event)

    def _show_state(self, *, announce: bool = False) -> None:
        on = self.active()
        active = bool(on)
        secondary = self.palette().color(QPalette.ColorRole.Text)
        secondary.setAlpha(SECONDARY_ALPHA)
        ink = self.palette().color(QPalette.ColorRole.Accent) if active else secondary
        self.face.setIcon(filter_icon(ink, active=active))
        self.clear_button.setIcon(close_icon(secondary.name()))
        self.clear_button.setEnabled(active)
        names = [self._actions[key].text() for key in on]
        self.face.setToolTip(f"{self._label} — {', '.join(names)}" if names else self._label)
        if self.face.property("active") != active:
            self.face.setProperty("active", active)
            self.face.style().unpolish(self.face)
            self.face.style().polish(self.face)
        if announce:
            self.changed.emit()
