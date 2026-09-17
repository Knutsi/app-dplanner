"""A panel a tab hosts beside its main surface.

A dock panel (``panels.py``) is anchored in one of the window's *areas* and follows whatever
the window is focused on — one instance, retargeted by the context. A panel inside a tab
follows *that tab*: there is one per tab, it is handed a context the tab constructs, so a
tab in the background never follows the tab in front, and it goes with the tab. The graph
tab's Problems list and the Tests tabs' Test panel are the two hosts.

What goes in the panel is another module's, so the host is handed a :class:`SidePanel` — a
name, a glyph and a way to build the widget — by the composition root, and never learns
whose. :class:`HostedSidePanel` is the hosting written once: the frame with its way out, the
strip button that opens it, and the splitter between the panel and the tab's own surface,
so the seam is the one every splitter in the application wears.

The widget it builds is reached through ``panels.py``'s ``ContextPanel`` protocol, which
such a panel already satisfies structurally. A panel may also answer :class:`ReadingPanel`
— one short string the strip's button shows beside the panel's glyph, and a signal when it
changes. That is how a count reaches the toolbar without the host learning what is being
counted, and it is a *reading*: the panel computes it on its own settled rebuild, and the
button reads what it last said.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QEvent, QSize, Qt, SignalInstance
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService
from dplanner.framework.panels import ContextPanel
from dplanner.framework.widgets import caption
from dplanner.theme.icons import ICON_SIZE, close_icon
from dplanner.theme.tokens import (
    CAPTION_GAP,
    CONTROL_HEIGHT,
    PANEL_MARGIN,
    SECONDARY_ALPHA,
    SECTION_GAP,
)

# A side panel opens at the width the window's own left area opens at, so a list of
# features reads the same whichever side of the seam it is on.
SIDE_PANEL_WIDTH = 280


@runtime_checkable
class ReadingPanel(Protocol):
    """A panel that has a short something to say on the strip that opens it.

    Optional — the host asks ``isinstance`` — so a panel with nothing to count implements
    nothing and its button is the glyph alone.
    """

    # A Qt signal carrying the new reading, connected by the host.
    reading_changed: SignalInstance

    def reading(self) -> str: ...


@dataclass(frozen=True)
class SidePanel:
    """What a tab hosts beside its main surface, named by the composition root."""

    title: str
    icon: Callable[[QColor], QIcon]
    build: Callable[[], QWidget]
    # The width the seam opens to when the panel is first shown; the user's after that.
    width: int = SIDE_PANEL_WIDTH


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


class PanelButton(QToolButton):
    """The strip's seat for the panel: the toggle, wearing its glyph and the panel's reading.

    A ``Toolbar`` renders a verb as a glyph with its words in the tooltip, which is right
    for nineteen verbs and wrong for the one control that has to say *how many*. So the
    panel's seat on the strip is a widget rather than a plain action button — the layout
    picker's arrangement — showing the panel spec's own glyph and whatever the panel last
    said about itself (a :class:`ReadingPanel`'s reading).

    It runs the verb through :meth:`ActionRegistry.run` like every other presenter, so the
    state gate holds and the preference is written in exactly one place; and it follows
    the verb's ``checked`` so the button is filled while the panel stands.

    It is **not** a ``#ToolbarButton``: a banded strip squares those, and a square is
    exactly what a control carrying a number cannot be. It wears the same look by being
    named in the same rules.
    """

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
        self.setObjectName("PanelButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCheckable(True)
        # Like every toolbar button: a click must not take the keyboard off the surface.
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


class HostedSidePanel:
    """A :class:`SidePanel` stood beside a tab's main surface, wired once.

    The host seats :attr:`button` on its strip, puts :attr:`split` in its page, feeds
    :meth:`show_context` from its own selection, and calls :meth:`set_shown` from its own
    preference verb — the one named by ``toggle``, which the frame's close button runs too,
    so the preference is written in exactly one place.
    """

    def __init__(
        self,
        spec: SidePanel,
        main: QWidget,
        *,
        toggle: str,
        actions: ActionRegistry,
        context: ContextService,
    ) -> None:
        self._spec = spec
        self.button = PanelButton(toggle, spec.icon, actions, context)
        self.content = spec.build()
        # A panel that has a reading — a count of what is wrong — says so on the strip's
        # button. One string: the host never learns what is being counted.
        if isinstance(self.content, ReadingPanel):
            self.button.set_reading(self.content.reading())
            self.content.reading_changed.connect(self.button.set_reading)
        self.frame = SidePanelFrame(
            spec.title,
            self.content,
            lambda: actions.run(toggle, context.current()),
        )
        # A splitter, so the seam between them is the one every splitter in the application
        # wears and the panel's width is the user's while the tab is open.
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(main)
        self.split.addWidget(self.frame)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setCollapsible(1, False)
        self.frame.hide()  # The host's preference, a line later, is what decides.

    def shown(self) -> bool:
        return not self.frame.isHidden()

    def set_shown(self, shown: bool) -> None:
        """Stand the panel or take it down; the button's face follows the verb it runs."""
        self.frame.setVisible(shown)
        if shown:
            self._give_the_panel_its_width()
        self.button.refresh()

    def show_context(self, context: Context) -> bool:
        return self.frame.show_context(context)

    def dispose(self) -> None:
        self.frame.dispose()

    def _give_the_panel_its_width(self) -> None:
        """Open the seam where the splitter has closed it.

        A splitter hands out the width it had when its children were added, and a tab is
        built before it is on screen — so a panel switched on later would arrive at nought
        pixels wide and read as nothing having happened.
        """
        width = self._spec.width
        main, panel = self.split.sizes()
        if panel >= width:
            return
        room = main + panel
        self.split.setSizes([max(room - width, width), width])
