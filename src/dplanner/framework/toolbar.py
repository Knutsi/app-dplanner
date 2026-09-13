"""Strips of controls a tab page carries, and the verbs on them.

:class:`Toolbar` is **the** strip of verbs (DESIGN.md's *Toolbars*): glyphs with their
words in tooltips, folding into a ``…`` menu, optionally cut into named bands. Its verbs
come either from the host (:meth:`Toolbar.add_verb`, a glyph and a slot) or from the action
registry (:meth:`Toolbar.add_action`), and a band may end in a *face*
(:meth:`Toolbar.add_menu_face`) — one glyph dropping a band of the menus down.

The registry stays the single source of truth — a presenter here renders a chosen subset of
specs as buttons, exactly as the menu bar renders all of them as QActions. Shortcuts stay
with the menu bar's QActions; a click here goes through ``registry.run``, so the state gate
holds even if a stale context left a button enabled. Strips live inside tabs, so unlike the
app-lifetime menu bar they must be ``dispose()``d when their tab closes.

**A strip renders the application's action state, not its own tab's.** One in a background
tab — or in a tab group the user is not in — shows what the *active* surface can do, because
there is one ``ContextService``. Invisible while only one tab is on screen; visible once the
window is split. If that ever matters, the fix is a ``set_active(bool)`` that greys the row
when its group is not the active one, not a context per group.

**A button may drop its verb's submenu down.** ``menus`` names, per action id, the
``(menu, submenu)`` whose entries belong under that button's arrow: the button runs its own
verb on a click and renders that child menu on the arrow — through ``fill_menu``, so it is
the menu, never a copy of it, and it is refilled on every open against the context and the
palette of that moment.

:class:`ActionToolbar` is the older presenter — registry-fed like the above, but a plain
row of *worded* buttons with no overflow of its own. The order table still wears it, and
moves onto :class:`Toolbar` when its design pass comes. Write nothing new on it.

A page's *own* controls — a selector, a spin box, a date — sit on the same :class:`Toolbar`
through ``add_widget``, beside its verbs; ``set_shown`` is how the host takes one away.
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
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.framework.action_menu import fill_menu
from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
    key_sequences,
)
from dplanner.framework.context import Context, ContextService
from dplanner.theme.cards import detail_font
from dplanner.theme.icons import (
    FILTER_ICON_W,
    ICON_SIZE,
    blank_icon,
    close_icon,
    filter_icon,
)
from dplanner.theme.tokens import (
    CAPTION_GAP,
    CONTROL_GAP,
    CONTROL_HEIGHT,
    DENSE_GAP,
    SECONDARY_ALPHA,
)


def action_words(spec: ActionSpec, state: ActionState) -> tuple[str, str]:
    """What a registry-fed button says: its words, and the standing explanation behind them.

    One definition for both presenters. A state that rewords a verb to carry a count or a
    refusal — *Delete 3 Steps*, *— pick a feature* — has to read the same on a strip of
    glyphs, where the words are the tooltip, as on a strip of words.
    """
    label = (state.label if state.label is not None else spec.label).replace("&", "")
    return label, spec.tip or label


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
            label, tip = action_words(spec, state)
            text = self._button_text.get(action_id, label)
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
            button.setToolTip(tip)

    def dispose(self) -> None:
        self._unsubscribe()


MORE = "…"
DIVIDER_INSET = 6  # A divider stops this far short of the controls' top and bottom.


@dataclass
class _Item:
    widget: QWidget
    # What the … menu lists when this item folds — one verb, or a whole group's. Empty for
    # a widget, which never enters the menu, and for a divider, which only parts.
    actions: Sequence[QAction] = ()
    divider: bool = False
    # Whether the host wants it on the strip at all: a selector with nothing to choose
    # between is left off, and the reflow must not put back what the host took away.
    shown: bool = True


class _Group(QWidget):
    """One labelled band of a strip: its buttons in a row, its name under them.

    The band is the unit — it is what a divider parts and what the … menu takes whole — so
    it is one widget rather than a run of items the reflow would have to keep together.
    Its glyphs are read as one set, so they sit ``DENSE_GAP`` apart where the bands
    themselves stand ``CONTROL_GAP`` apart.
    """

    def __init__(self, label: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.verbs: list[QAction] = []
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CAPTION_GAP if label else 0)
        # Added to its parent before it is filled: a parentless layout given widgets first
        # leaves QWidgetItem wrappers alive on the Python side (CLAUDE.md, §14).
        self.row = QHBoxLayout()
        column.addLayout(self.row)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(DENSE_GAP)
        self.caption: QLabel | None = None
        if label:
            self.caption = QLabel(label, self)
            self.caption.setObjectName("ToolbarGroupLabel")
            self.caption.setFont(detail_font(self.caption.font()))
            self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(self.caption)

    def hold(self, widget: QWidget, action: QAction | None) -> None:
        widget.setFixedHeight(CONTROL_HEIGHT)
        self.row.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
        if action is not None:
            self.verbs.append(action)


def _divider(parent: QWidget) -> QWidget:
    """The hairline between two bands, hung from the top so it parts the buttons.

    A band is taller than a control — its name sits under it — and a rule centred on the
    whole band would hang below the row it is parting. The line keeps the controls'
    inset and the space under it is the label's.
    """
    holder = QWidget(parent)
    holder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, DIVIDER_INSET, 0, 0)
    column.setSpacing(0)
    rule = QFrame(holder)
    rule.setObjectName("ToolbarDivider")
    rule.setFixedSize(1, CONTROL_HEIGHT - 2 * DIVIDER_INSET)
    column.addWidget(rule)
    column.addStretch(1)
    return holder


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

    **A strip may be cut into labelled bands** (:meth:`add_group`), which is what a drawing
    surface's strip is: nineteen glyphs in a row are nineteen riddles, and six named bands
    of three are a tool palette. The band is then the unit — the divider parts bands, and
    the … menu takes a band whole, with a rule where each begins — because half a band on
    the strip and half in the menu is worse than all of it in either.

    **A verb may come from the registry** (:meth:`add_action`), which is how a real surface
    fills one: the glyph is the spec's, the words and the state are restated on every
    context change, and an arrow may drop the verb's own child menu down.
    """

    def __init__(self, parent: QWidget | None = None, *, dense: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("ControlBar")
        self.setProperty("dense", dense)  # `#ControlBar[dense="true"]` narrows the buttons.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._items: list[_Item] = []
        self._painters: dict[QAction, Callable[[QColor], QIcon]] = {}
        self._tips: dict[QAction, str] = {}
        # The shortcut a tooltip prints. A registry-fed verb never *takes* the key — the
        # menu bar's QAction owns it, and a second QAction with the same sequence makes
        # both ambiguous and fires neither — so the words are all this strip carries.
        self._keys: dict[QAction, str] = {}
        self._group: _Group | None = None
        # Registry-fed verbs: the id, its action and its button, restated together.
        self._bound: list[tuple[str, QAction, QToolButton]] = []
        # Action → the popup its arrow drops, and how that popup is filled when it opens.
        # A filler rather than a menu name, because what an arrow offers is as often *data*
        # — the launch profiles under Compile with Agent — as a band of the action table.
        self._popups: dict[QAction, tuple[QMenu, Callable[[QMenu], None]]] = {}
        self._faces: dict[QAction, QToolButton] = {}
        self._registry: ActionRegistry | None = None
        self._context: ContextService | None = None
        self._unsubscribe: Callable[[], None] | None = None
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
        self._layout.addWidget(self._more, 0, Qt.AlignmentFlag.AlignTop)
        self._layout.addStretch(1)

    # -- filling it --------------------------------------------------------------------

    def add_group(self, label: str = "") -> None:
        """Open a band: what follows lands in it, under ``label``, parted from the last.

        The bands stand ``CONTROL_GAP`` apart whatever the strip's own gap is — a dense
        strip is dense *within* a band, and two bands four pixels apart would be one — and
        a banded strip's glyph buttons are squares (``#ControlBar[banded="true"]``): a tool
        palette is a grid of targets of one size, where a strip that answers a question
        about the thing on screen would rather seat one more glyph.
        """
        self._layout.setSpacing(CONTROL_GAP)
        if not self.property("banded"):
            self.setProperty("banded", True)
            self.style().unpolish(self)
            self.style().polish(self)
        if self._items:
            self.add_divider()
        group = _Group(label, self)
        self._group = group
        self._place(_Item(group, group.verbs))

    def add_verb(
        self,
        text: str,
        icon: Callable[[QColor], QIcon],
        slot: Callable[[], object],
        *,
        shortcut: str = "",
        keys: str = "",
        checkable: bool = False,
        tip: str = "",
    ) -> QAction:
        """A glyph on the strip; ``text`` (and the key) is its tooltip and its words in
        the … menu. The returned action is what a host enables, checks and rewords.

        ``shortcut`` **claims** the key: the action is this strip's, and a strip lives in
        a window, so the key then fires wherever the window has focus. ``keys`` only
        **says** it — for a key some other widget owns, which is what a verb acting on one
        editor's caret needs (a ``QShortcut`` on the editor at ``WidgetShortcut``). Ctrl+B
        on a toolbar's own action would reach every text field in the window, and a second
        action carrying the same sequence makes both ambiguous and fires neither.

        ``tip`` is for a verb that has more to say than its words — a registered
        ``ActionSpec.tip``, say. It stands in the tooltip while the words still name the
        entry in the … menu, so a host that rewords an action to carry a refusal does not
        lose the standing explanation with it.
        """
        action = self._verb(text, icon, checkable=checkable, tip=tip, keys=keys or shortcut)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False: slot())
        self._seat(self._glyph(action), action)
        return action

    def add_action(
        self,
        registry: ActionRegistry,
        context: ContextService,
        action_id: str,
        *,
        menu: tuple[str, str] | None = None,
        data_menu: str | None = None,
    ) -> QAction:
        """A verb the registry owns, restated on every context change.

        The glyph is ``ActionSpec.icon``, the words and the reason come from the spec and
        its state (:func:`action_words`), and a click goes through ``registry.run``, so the
        state gate holds even if a stale context left a button enabled. ``menu`` names the
        ``(menu, submenu)`` the button's arrow drops down — the child menu itself, refilled
        on every open, never a copy of it — and ``data_menu`` names a ``DataMenuSpec``
        instead, for a verb whose other ways of running it are data rather than a band of
        the table: the launch profiles under *Compile with Agent*, which `fill_menu` leaves
        out of a named-submenu render precisely because a data child menu belongs to its
        menu rather than to one of its submenus.
        """
        self._bind(registry, context)
        spec = registry.spec(action_id)
        keys = key_sequences(spec.shortcut)
        action = self._verb(
            spec.label.replace("&", ""),
            spec.icon if spec.icon is not None else blank_icon,
            checkable=False,
            tip=spec.tip,
            keys=keys[0].toString(QKeySequence.SequenceFormat.NativeText) if keys else "",
        )
        action.triggered.connect(
            lambda _checked=False, a=action_id: registry.run(a, context.current())
        )
        button = self._glyph(action)
        if menu is not None:
            self._arrow(button, action, self._table_fill(menu[0], menu[1]))
        elif data_menu is not None:
            self._arrow(button, action, registry.data_menu(data_menu).fill)
        self._seat(button, action)
        self._bound.append((action_id, action, button))
        self._state(action_id, action, button, context.current())
        return action

    def add_menu_face(
        self,
        text: str,
        icon: Callable[[QColor], QIcon],
        registry: ActionRegistry,
        context: ContextService,
        menu: str,
        *,
        submenu: str | None = None,
        group: str | None = None,
    ) -> QAction:
        """A button that is only a menu: one glyph dropping a menu of the action table.

        Not :meth:`add_action` with an arrow — there is no verb under the face, so there is
        no second target and no hairline parting two halves. Folded into the … menu it
        becomes a child menu of the same entries, so a band of one face is still reachable
        from a strip too narrow to show it.
        """
        self._bind(registry, context)
        action = self._verb(text, icon, checkable=False, tip="", keys="")
        popup = QMenu(self)
        popup.aboutToShow.connect(lambda: self._refill(action))
        self._popups[action] = (popup, self._table_fill(menu, submenu, group))
        action.setMenu(popup)  # So the … menu shows the face as a child menu of the same.
        # Not ``setDefaultAction``: a QToolButton takes its menu from its default action,
        # and giving it one of its own lets the action go — the face then renders its
        # words in place of the glyph. It wears the action's face instead, and :meth:`_ink`
        # keeps the two together.
        button = QToolButton(self)
        button.setObjectName("ToolbarButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setIcon(action.icon())
        button.setToolTip(action.toolTip())
        button.setMenu(popup)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # The layout picker's look: a face that drops choices down, with the arrow's room.
        button.setProperty("face", True)
        self._faces[action] = button
        self._seat(button, action)
        return action

    def add_widget(self, widget: QWidget) -> QWidget:
        """A control that is not a verb — a filter, a grouping — among the verbs."""
        widget.setParent(self)
        self._seat(widget, None)
        return widget

    def add_divider(self) -> None:
        self._place(_Item(_divider(self), (), divider=True))

    def set_shown(self, widget: QWidget, shown: bool) -> None:
        """Whether a control seated here belongs on the strip right now — a selector with
        nothing to choose between, a field only one pick needs.

        The strip decides what fits, so a host that hid the widget itself would see it come
        back on the next reflow; this is what it asks instead. A widget inside a band is
        shown or hidden directly, since a band never re-shows its own.
        """
        for item in self._items:
            if item.widget is widget:
                item.shown = shown
                self._reflow()
                return
        widget.setVisible(shown)

    def is_shown(self, widget: QWidget) -> bool:
        """What :meth:`set_shown` last said of a control — whether it belongs on the strip,
        which a strip too narrow for it, or never laid out, cannot answer by hiding it."""
        return next((item.shown for item in self._items if item.widget is widget), True)

    # -- the pieces a seat is made of ----------------------------------------------------

    def _verb(
        self,
        text: str,
        icon: Callable[[QColor], QIcon],
        *,
        checkable: bool,
        tip: str,
        keys: str,
    ) -> QAction:
        action = QAction(text, self)
        action.setCheckable(checkable)
        if tip:
            self._tips[action] = tip
        if keys:
            self._keys[action] = keys
        action.changed.connect(lambda a=action: self._retip(a))
        # A checked button is filled with the accent, so its glyph changes ink with it.
        # `toggled` and not `changed`: re-inking inside `changed` would re-enter it.
        action.toggled.connect(lambda _on, a=action: self._ink(a))
        self._painters[action] = icon
        self._retip(action)
        # Inked here, before any button takes it as its default action: a QToolButton
        # copies what the action has at that moment, and one given a null icon renders
        # its words instead.
        self._ink(action)
        return action

    def _glyph(self, action: QAction) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("ToolbarButton")
        # A toolbar never takes the keyboard. Without this, clicking a button moves focus
        # off the surface it just acted on, and the next keystroke goes nowhere — which a
        # canvas with its own key bindings notices immediately.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))  # Qt's toolbar default is 24.
        button.setDefaultAction(action)
        return button

    def _table_fill(
        self, menu: str, submenu: str | None = None, group: str | None = None
    ) -> Callable[[QMenu], None]:
        """A filler that renders one child menu — or one band — of the action table."""

        def fill(popup: QMenu) -> None:
            assert self._registry is not None and self._context is not None
            fill_menu(popup, self._registry, self._context, menu, submenu, group)

        return fill

    def _arrow(self, button: QToolButton, action: QAction, fill: Callable[[QMenu], None]) -> None:
        """The arrow beside a button, rendering one child menu of the action table.

        ``MenuButtonPopup``, not ``InstantPopup``: the button half still runs the verb, so
        Sort lays the graph out the layered way and the arrow is only for the rest of the
        family. Qt sizes the arrow from ``PM_MenuButtonIndicator`` — about ten pixels, both
        unaimable and a thing that reads as a rendering fault — so ``hasMenu`` is what lets
        the theme widen it and leave the glyph its room.
        """
        popup = QMenu(button)
        popup.aboutToShow.connect(lambda: self._refill(action))
        self._popups[action] = (popup, fill)
        button.setMenu(popup)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setProperty("hasMenu", True)

    def _seat(self, widget: QWidget, action: QAction | None) -> None:
        if self._group is not None:
            self._group.hold(widget, action)
            self._reflow()
            return
        self._place(_Item(widget, () if action is None else (action,)))

    def _place(self, item: _Item) -> None:
        if not item.divider and not isinstance(item.widget, _Group):
            # One height for every control, in code: the styles' content heights agree for
            # a worded button and a combo and disagree by three pixels for one with a menu.
            item.widget.setFixedHeight(CONTROL_HEIGHT)
        self._layout.insertWidget(
            self._layout.indexOf(self._more), item.widget, 0, Qt.AlignmentFlag.AlignTop
        )
        self._items.append(item)
        self._reflow()

    def verbs(self) -> list[QAction]:
        return [action for item in self._items for action in item.actions]

    # -- what the registry says ----------------------------------------------------------

    def _bind(self, registry: ActionRegistry, context: ContextService) -> None:
        if self._unsubscribe is None:
            self._registry = registry
            self._context = context
            self._unsubscribe = context.changed.connect(self._restate)

    def _restate(self, context: Context) -> None:
        for action_id, action, button in self._bound:
            self._state(action_id, action, button, context)
        self._reflow()

    def _state(
        self, action_id: str, action: QAction, button: QToolButton, context: Context
    ) -> None:
        assert self._registry is not None
        spec = self._registry.spec(action_id)
        state = spec.state(context)
        label, tip = action_words(spec, state)
        action.setText(label)
        self._tips[action] = tip
        self._retip(action)
        action.setEnabled(state.enabled)
        if state.checked is not None:
            action.setCheckable(True)
            action.setChecked(state.checked)
        # A QToolButton follows its default action's text, icon, state and tooltip, but
        # not its visibility; and the reflow must not put back what a state took away.
        action.setVisible(state.visible)
        button.setVisible(state.visible)

    def _refill(self, action: QAction) -> None:
        popup, fill = self._popups[action]
        popup.clear()
        fill(popup)

    def menu_for(self, action_id: str) -> QMenu | None:
        """The dropdown a registered verb's button carries, filled as it would open."""
        for bound_id, action, _button in self._bound:
            if bound_id == action_id and action in self._popups:
                self._refill(action)
                return self._popups[action][0]
        return None

    def face_menu(self, action: QAction) -> QMenu:
        """The menu a face drops, filled as it would open — :meth:`menu_for` for a face."""
        self._refill(action)
        return self._popups[action][0]

    def button_for(self, action_id: str) -> QToolButton | None:
        """The button one registered verb wears — how a test asks what the row is saying."""
        for bound_id, _action, button in self._bound:
            if bound_id == action_id:
                return button
        return None

    def dispose(self) -> None:
        """A strip lives inside a tab and must let the context go when the tab closes."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # -- the words -----------------------------------------------------------------------

    def _retip(self, action: QAction) -> None:
        """The verb's words and its key, and what else it has to say under them.

        A glyph says nothing until somebody hovers it, so the words must be the first line
        — a tooltip that carries only the standing explanation leaves the verb unnamed.
        The explanation is worth having too, so it goes on a second line rather than
        instead.
        """
        words = action.text()
        keys = self._keys.get(action) or (
            ""
            if action.shortcut().isEmpty()
            else action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        )
        if keys:
            words = f"{words}  {keys}"
        said = self._tips.get(action, "")
        if said and said != action.text():
            words = f"{words}\n{said}"
        if action.toolTip() != words:
            action.setToolTip(words)

    def _inks(self) -> tuple[QColor, QColor]:
        """The quiet ink, and the one a glyph takes on an accent-filled button."""
        secondary = self.palette().color(QPalette.ColorRole.Text)
        secondary.setAlpha(SECONDARY_ALPHA)
        # BrightText carries the theme's $ON_ACCENT: a checked button is filled with the
        # accent, and a glyph left in the quiet tone disappears into it.
        return secondary, self.palette().color(QPalette.ColorRole.BrightText)

    def _ink(self, action: QAction) -> None:
        painter = self._painters.get(action)
        if painter is None:
            return
        secondary, on_accent = self._inks()
        icon = painter(on_accent if action.isChecked() else secondary)
        action.setIcon(icon)
        face = self._faces.get(action)
        if face is not None:
            face.setIcon(icon)  # A face wears the action's glyph without following it.

    def _reink(self) -> None:
        for action in self._painters:
            self._ink(action)

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
        """The controls that belong on the strip and did not fit — never what was taken off
        it, and never a divider, which parts rather than folds."""
        return [
            item
            for item in self._items
            if not item.divider and self._wanted(item) and item.widget.isHidden()
        ]

    def _wanted(self, item: _Item) -> bool:
        """Whether an item belongs on the strip at all: the host has not taken it off, and a
        lone verb's action is visible — a registry state may hide one."""
        if not item.shown:
            return False
        if len(item.actions) == 1 and not isinstance(item.widget, _Group):
            return item.actions[0].isVisible()
        return True

    def _reflow(self) -> None:
        """Show what fits from the left; fold the rest into the … menu.

        What the host took off the strip, or a state hid, is neither measured, shown nor
        listed: a reflow that set every item's visibility from the room alone put back what
        somebody had deliberately taken away.
        """
        gap = self._layout.spacing()
        wanted = [item for item in self._items if self._wanted(item)]
        widths = [item.widget.sizeHint().width() for item in wanted]
        room = self.width()
        shown = len(wanted)
        if sum(widths) + gap * max(0, len(widths) - 1) > room:
            room -= self._more.sizeHint().width() + gap
            used = 0
            shown = 0
            for width in widths:
                if used + width > room:
                    break
                used += width + gap
                shown += 1
        # A divider parts two controls or nothing: never at either end of what is shown, and
        # never beside another, which is what a control taken off between two would leave.
        on: set[int] = set()
        pending: _Item | None = None
        for item in wanted[:shown]:
            if item.divider:
                pending = item if on else None
                continue
            if pending is not None:
                on.add(id(pending))
                pending = None
            on.add(id(item))
        for item in self._items:
            item.widget.setVisible(id(item) in on)
        self._more.setVisible(any(not item.divider and id(item) not in on for item in wanted))

    def _fill_more(self) -> None:
        self._menu.clear()
        pending_divider = False
        for item in self._items:
            if not item.widget.isHidden() or not self._wanted(item):
                continue
            if item.divider:
                pending_divider = bool(self._menu.actions())
                continue
            listed = [action for action in item.actions if action.isVisible()]
            if not listed:
                continue  # A widget never enters the menu, and nor does an empty band.
            if pending_divider:
                self._menu.addSeparator()
                pending_divider = False
            for action in listed:
                self._menu.addAction(action)


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
