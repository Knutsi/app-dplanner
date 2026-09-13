"""The panel beside the canvas, inside the project tab.

A dock panel is anchored in one of the window's *areas* and follows whatever the window is
focused on; this one is inside one tab and follows that tab's project, which is why it is
not a ``PanelSpec``. What goes in it is another module's — the Features list is the first —
so the composition root hands over a :class:`SidePanel`: a name, a glyph and a way to build
the widget. This package never learns whose.

The widget it builds is reached through ``framework/panels.py``'s ``ContextPanel``
protocol, which such a panel already satisfies structurally: it is told which project to
show by being handed a context naming *this tab's* project, so a tab in the background
never follows the tab in front.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from dplanner.framework.context import Context
from dplanner.framework.panels import ContextPanel
from dplanner.framework.widgets import caption
from dplanner.theme.icons import ICON_SIZE, close_icon
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECONDARY_ALPHA, SECTION_GAP

# A side panel opens at the width the window's own left area opens at, so a list of
# features reads the same whichever side of the seam it is on.
SIDE_PANEL_WIDTH = 280


@dataclass(frozen=True)
class SidePanel:
    """What the graph tab hosts beside the canvas, named by the composition root."""

    title: str
    icon: Callable[[QColor], QIcon]
    build: Callable[[], QWidget]


class SidePanelFrame(QWidget):
    """The panel's header and its content: the dock's frame, for a tab.

    The header is the dock's — the name in ``#InspectorCaption``, 16 from the sides, 12
    above and 6 below — so a panel reads the same on either side of the move. What it
    gains is a way out, because a panel inside a tab has no header right-click offering
    one; what it draws is no edge, because the seam beside it belongs to the splitter.
    """

    def __init__(self, title: str, content: QWidget, close: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        # Added to its parent before it is filled (CLAUDE.md's layout-item rule).
        header = QHBoxLayout()
        column.addLayout(header)
        header.setContentsMargins(PANEL_MARGIN, SECTION_GAP, SECTION_GAP, CAPTION_GAP)
        header.setSpacing(CAPTION_GAP)
        header.addWidget(caption(title, self))
        header.addStretch(1)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("SidePanelClose")
        self.close_button.setToolTip(f"Hide the {title} panel")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.close_button.clicked.connect(lambda _checked=False: close())
        header.addWidget(self.close_button)
        self.content = content
        content.setParent(self)
        column.addWidget(content, 1)
        self._paint()

    def show_context(self, context: Context) -> bool:
        """Point the panel at a context — the dock's one call, made by the tab instead.

        A panel that does not follow a context (a fixed list) simply has nothing to say to
        this, and stands.
        """
        if isinstance(self.content, ContextPanel):
            return self.content.show_context(context)
        return True

    def dispose(self) -> None:
        """Let the panel go when the tab does, as the dock does when the window goes."""
        if isinstance(self.content, ContextPanel):
            self.content.dispose()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._paint()  # A glyph carries the ink it was painted in.
        super().changeEvent(event)

    def _paint(self) -> None:
        ink = self.palette().color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        self.close_button.setIcon(close_icon(ink.name()))
