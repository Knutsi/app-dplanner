"""The strip of verbs over the canvas.

It renders **action ids and nothing else**. The step verbs next door, the app shell's undo
pair and the order module's ``order.open`` all arrive the same way, and this module imports
none of them — the registry is the only thing between them, so adding a button is adding a
string to :data:`GROUPS`.

Grouping is the only structure a toolbar has, so it is spelled out here rather than inferred
from the menus, where these nine verbs sit under four different headings. A hairline is drawn
between groups; :mod:`dplanner.framework.toolbar` renders one group each and knows nothing
about the others.

Every button is its glyph alone with the spec's label left as the tooltip — except the mode
switches, which are words and no glyph. A mode you are in has to be readable at a glance, and
a checked button is filled with the accent, where a glyph painted in the secondary text colour
would have nothing left to say.

New is worded too: it is the verb the strip exists for, and a plus alone reads as a
decoration.
"""

from collections.abc import Callable, Sequence

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import ActionToolbar
from dplanner.theme.icons import (
    edit_icon,
    frame_icon,
    list_icon,
    plus_icon,
    redo_icon,
    trash_icon,
    undo_icon,
    unlink_icon,
)

GROUPS: tuple[tuple[str, ...], ...] = (
    ("steps.new", "steps.rename", "steps.delete"),
    ("steps.connect", "steps.unlink"),
    ("regions.new",),
    ("appshell.undo", "appshell.redo"),
    ("canvas.frame", "order.open"),
)

# The two mode switches and New are worded; everything else is its glyph.
_WORDED = {"steps.new": "New", "steps.connect": "Connect", "regions.new": "Region"}
BUTTON_TEXT = {action_id: _WORDED.get(action_id, "") for group in GROUPS for action_id in group}

ICONS: dict[str, Callable[[str], QIcon]] = {
    "steps.new": plus_icon,
    "steps.rename": edit_icon,
    "steps.delete": trash_icon,
    "steps.unlink": unlink_icon,
    "appshell.undo": undo_icon,
    "appshell.redo": redo_icon,
    "canvas.frame": frame_icon,
    "order.open": list_icon,
}

# DESIGN.md's 4-point scale: the strip breathes at 8, and 12 separates one group from the next.
STRIP_MARGIN = 8
GROUP_GAP = 12


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
        for index, group in enumerate(groups):
            if index:
                # A painted hairline rather than a QFrame VLine: a styled QFrame draws its
                # line from the palette, which is the one colour here the theme cannot reach.
                rule = QWidget(self)
                rule.setObjectName("ToolbarRule")
                rule.setFixedWidth(1)
                row.addWidget(rule)
            bar = ActionToolbar(actions, context, tuple(group), BUTTON_TEXT, self)
            row.addWidget(bar)
            self._bars.append(bar)
        row.addStretch(1)
        if trailing is not None:
            # The far end of the strip — the layout picker's seat, owned by whoever made it.
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
