"""The strip's button for the panel beside the canvas: its glyph, and its reading.

A ``Toolbar`` renders a verb as a glyph with its words in the tooltip, which is right for
nineteen verbs and wrong for the one control that has to say *how many*. So the panel's
seat on the strip is a widget rather than a plain action button — the layout picker's
arrangement — showing the panel spec's own glyph and whatever the panel last said about
itself (``SidePanel``'s ``ReadingPanel``).

It runs the verb through :meth:`ActionRegistry.run` like every other presenter, so the
state gate holds and the preference is written in exactly one place; and it follows the
verb's ``checked`` so the button is filled while the panel stands.

It is **not** a `#ToolbarButton`: a banded strip squares those, and a square is exactly
what a control carrying a number cannot be. It wears the same look by being named in the
same rules.
"""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import CONTROL_HEIGHT


class PanelButton(QToolButton):
    """The panel toggle, wearing its glyph and the panel's own reading."""

    def __init__(
        self,
        action_id: str,
        icon: Callable[[QColor], QIcon],
        actions: ActionRegistry,
        context: ContextService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._action_id = action_id
        self._icon = icon
        self._actions = actions
        self._context = context
        # Its own name, not ``#ToolbarButton``: a banded strip squares its glyph buttons
        # (DESIGN.md's *Toolbars*), and this one carries a count beside its glyph. It wears
        # the same quiet bordered look and the same checked fill; it is only not a square.
        self.setObjectName("PanelButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCheckable(True)
        # Like every toolbar button: a click must not take the keyboard off the canvas.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._run)
        self._reading = ""
        self.refresh()

    def set_reading(self, reading: str) -> None:
        """What the panel says about itself — "(4)", or "" for the glyph alone."""
        self._reading = reading
        self.setText(reading)

    def refresh(self) -> None:
        """Follow the verb: its words in the tooltip, its checked state on the face."""
        spec = self._actions.spec(self._action_id)
        state = spec.state(self._context.current())
        words = (state.label or spec.label).replace("&", "")
        self.setToolTip(spec.tip or words)
        self.setChecked(bool(state.checked))
        self.setText(self._reading)
        self.setIcon(self._icon(self._ink()))

    def _ink(self) -> QColor:
        """A checked button is filled with the accent, so its glyph takes ``$ON_ACCENT``
        — the palette's BrightText — exactly as a checked verb's does on the strip."""
        palette = self.palette()
        role = palette.ColorRole.BrightText if self.isChecked() else palette.ColorRole.Text
        return palette.color(role)

    def _run(self, _checked: bool = False) -> None:
        self._actions.run(self._action_id, self._context.current())
        self.refresh()
