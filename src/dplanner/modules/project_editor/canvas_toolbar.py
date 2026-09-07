"""The strip of verbs over the canvas.

It renders **action ids and nothing else**. The step verbs next door, the app shell's undo
pair and the order module's ``order.open`` all arrive the same way, and this module imports
none of them — the registry is the only thing between them, so adding a button is adding a
string to :data:`GROUPS`.

Grouping is the only structure a toolbar has, so it is spelled out here rather than inferred
from the menus, where these verbs sit under four different headings. A hairline is drawn
between groups; :mod:`dplanner.framework.toolbar` renders one group each and knows nothing
about the others.

The row itself is a ``QToolBar`` (through ``framework/toolbar.py``'s ``control_bar``): a
canvas can be dragged narrower than its own strip, and a plain layout answers that by
shrinking every button until the words are riddles. A toolbar answers it by moving the
groups that no longer fit into its » menu.

Every button is its glyph alone with the spec's label left as the tooltip — except the
switches, which are words and no glyph: the three modes, and the three marks at the far end.
A mode you are in, or a mark you have on, has to be readable at a glance, and a checked button
is filled with the accent, where a glyph painted in the secondary text colour would have
nothing left to say.

New is worded too: it is the verb the strip exists for, and a plus alone reads as a
decoration.
"""

from collections.abc import Callable, Sequence

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import ActionToolbar, control_bar
from dplanner.theme.icons import (
    edit_icon,
    frame_icon,
    isolate_icon,
    lasso_icon,
    list_icon,
    plus_icon,
    redo_icon,
    sort_icon,
    trash_icon,
    undo_icon,
    unlink_icon,
)

GROUPS: tuple[tuple[str, ...], ...] = (
    ("steps.new", "steps.rename", "steps.delete"),
    (
        "steps.lasso",
        "steps.connect",
        "steps.redirect_to",
        "steps.unlink",
        "steps.isolate",
    ),
    ("canvas.sort_flow", "canvas.divide_vertical", "regions.new"),
    ("appshell.undo", "appshell.redo"),
    ("canvas.frame", "order.open"),
    ("canvas.mark_starts", "canvas.mark_ends", "canvas.mark_orphans"),
)

# Which child menu a button drops down. The button half still runs its own verb — Sort
# lays the graph out the layered way, Divide cuts upright, Redirect moves the arrowheads —
# and the arrow offers the rest of the family, rendered from the action table rather than
# copied, so a sort added to the menus appears here having touched nothing.
MENUS: dict[str, tuple[str, str]] = {
    "canvas.sort_flow": ("Graph", "Sort"),
    "canvas.divide_vertical": ("Graph", "Divide"),
    "steps.redirect_to": ("Step", "Redirect"),
}

# The switches and New are worded; everything else is its glyph. A button that drops a
# family down is worded for the family, not for the one verb its front half runs — its
# tooltip and its menu say which that is.
_WORDED = {
    "steps.new": "New",
    "steps.lasso": "Lasso",
    "steps.connect": "Connect",
    "steps.redirect_to": "Redirect",
    "canvas.divide_vertical": "Divide",
    "regions.new": "Region",
    "canvas.mark_starts": "Starts",
    "canvas.mark_ends": "Ends",
    "canvas.mark_orphans": "Orphans",
}
BUTTON_TEXT = {action_id: _WORDED.get(action_id, "") for group in GROUPS for action_id in group}

ICONS: dict[str, Callable[[str], QIcon]] = {
    "steps.new": plus_icon,
    "steps.lasso": lasso_icon,
    "steps.rename": edit_icon,
    "steps.delete": trash_icon,
    "steps.unlink": unlink_icon,
    "steps.isolate": isolate_icon,
    "canvas.sort_flow": sort_icon,
    "appshell.undo": undo_icon,
    "appshell.redo": redo_icon,
    "canvas.frame": frame_icon,
    "order.open": list_icon,
}

# DESIGN.md's 4-point scale: the strip breathes at 8, and 12 separates one group from the next.
STRIP_MARGIN = 8
GROUP_GAP = 12
# As tall as a button, so the hairline reads as a rule between groups rather than a tick.
RULE_HEIGHT = 24


class CanvasToolbar(QWidget):
    """One row of action buttons, repainted when the theme changes."""

    def __init__(
        self,
        actions: ActionRegistry,
        context: ContextService,
        theme: ThemeService,
        parent: QWidget | None = None,
        groups: Sequence[Sequence[str]] = GROUPS,
        trailing: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasToolbar")
        self._bars: list[ActionToolbar] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        row.setSpacing(GROUP_GAP)
        # The groups live in a QToolBar rather than straight in the row, for the one thing a
        # QToolBar does that a layout cannot: too narrow for its contents it grows the »
        # button and puts the tail in a menu, where a plain row shrinks every button until
        # "Divide" reads "D…e". A canvas can always be dragged narrower than its own strip,
        # so this is the only shape that stays legible — and what overflows is a whole group,
        # since the toolbar's items are the groups.
        strip = control_bar(self)
        inner = strip.layout()
        if inner is not None:
            inner.setSpacing(GROUP_GAP)
        for index, group in enumerate(groups):
            if index:
                # A painted hairline rather than a QFrame VLine: a styled QFrame draws its
                # line from the palette, which is the one colour here the theme cannot reach.
                rule = QWidget(self)
                rule.setObjectName("ToolbarRule")
                rule.setFixedWidth(1)
                # A toolbar gives a widget its size hint, and a bare QWidget's is nothing:
                # in the row it used to live in, the hairline was stretched to the row's
                # height for free. It has to ask now.
                rule.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
                rule.setMinimumHeight(RULE_HEIGHT)
                strip.addWidget(rule)
            bar = ActionToolbar(actions, context, tuple(group), BUTTON_TEXT, self, MENUS)
            strip.addWidget(bar)
            self._bars.append(bar)
        row.addWidget(strip, 1)
        if trailing is not None:
            # The far end of the strip — the layout picker's seat, owned by whoever made it.
            # Outside the toolbar, so it is the one thing that never overflows: it names the
            # arrangement the canvas is showing, which is a fact about the tab and not a verb.
            row.addWidget(trailing)

        self._unsubscribe = theme.changed.connect(lambda _theme: self._paint(theme))
        self._paint(theme)

    def button(self, action_id: str) -> QToolButton | None:
        """The button for one action id — how a test asks what the row is saying."""
        for bar in self._bars:
            found = bar._buttons.get(action_id)
            if found is not None:
                return found
        return None

    def menu_for(self, action_id: str) -> QMenu | None:
        """The child menu a button's arrow drops, filled as it would open."""
        for bar in self._bars:
            found = bar.menu_for(action_id)
            if found is not None:
                return found
        return None

    def dispose(self) -> None:
        """Toolbars live inside a tab and must let go of the context when it closes."""
        self._unsubscribe()
        for bar in self._bars:
            bar.dispose()
        self._bars.clear()

    def _paint(self, theme: ThemeService) -> None:
        colour = theme.current.text_secondary
        icons = {action_id: paint(colour) for action_id, paint in ICONS.items()}
        for bar in self._bars:
            bar.set_button_icons(icons)
