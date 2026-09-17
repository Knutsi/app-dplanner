"""A panel a tab hosts beside its main surface: the frame, the strip button, the seam.

Every test builds the hosting standalone — no window, no session — because that is what
``HostedSidePanel`` promises it can be: a tab hands it a spec and a surface and gets back a
splitter, a button and a frame, wired to one verb.
"""

import pytest
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QLabel, QWidget

from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
    MenuStructure,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    selection_uri,
)
from dplanner.framework.side_panel import HostedSidePanel, SidePanel, SidePanelFrame
from dplanner.menus import MENU_STRUCTURE

TOGGLE = "graph.side_panel"


def glyph(_color: QColor) -> QIcon:
    return QIcon()


class Counting(QWidget):
    """A panel with a reading and a context to follow — both optional contracts at once."""

    reading_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.target: str | None = None
        self.disposed = False

    def reading(self) -> str:
        return "(4)"

    def show_context(self, context: Context) -> bool:
        self.target = context.selected_entity("thing")
        return self.target is not None

    def dispose(self) -> None:
        self.disposed = True


class Preference:
    """The host's own preference verb: what the button and the frame's close both run."""

    def __init__(self) -> None:
        self.shown = False
        self.actions = ActionRegistry(MenuStructure(MENU_STRUCTURE))
        self.actions.register(
            ActionSpec(
                id=TOGGLE,
                label="&Things",
                menu="Graph",
                group="panels",
                state=lambda _context: ActionState(checked=self.shown),
                run=self._toggle,
            )
        )

    def _toggle(self, _context: Context) -> None:
        self.shown = not self.shown


@pytest.fixture
def preference():
    return Preference()


@pytest.fixture
def hosted(app, preference):
    content = Counting()
    made = HostedSidePanel(
        SidePanel("Things", glyph, lambda: content, width=300),
        QLabel("the surface"),
        toggle=TOGGLE,
        actions=preference.actions,
        context=ContextService(),
    )
    made.split.resize(1000, 600)
    yield made
    made.dispose()
    made.split.deleteLater()


def test_the_frame_follows_a_context_without_hiding_itself(app):
    content = Counting()
    frame = SidePanelFrame("Things", content, lambda: None)
    try:
        picked = Context({SCOPE_SELECTION: (ContextNode(selection_uri("thing", "one")),)})
        assert frame.show_context(picked) and content.target == "one"
        assert not frame.show_context(Context({}))  # Off screen is the host's call.
        frame.dispose()
        assert content.disposed
    finally:
        frame.deleteLater()


def test_a_fixed_list_has_nothing_to_say_to_a_context_and_stands(app):
    frame = SidePanelFrame("Things", QLabel("a list"), lambda: None)
    try:
        assert frame.show_context(Context({}))
    finally:
        frame.deleteLater()


def test_the_panel_is_down_until_shown_and_the_seam_opens_to_its_width(hosted):
    assert not hosted.shown() and hosted.frame.isHidden()
    hosted.set_shown(True)
    assert hosted.shown()
    _surface, panel = hosted.split.sizes()
    assert panel == 300


def test_a_wider_seam_the_user_opened_is_left_alone(hosted):
    hosted.set_shown(True)
    hosted.split.setSizes([500, 500])  # The user dragged the seam.
    hosted.set_shown(False)
    hosted.set_shown(True)
    assert hosted.split.sizes()[1] == 500


def test_the_button_and_the_close_both_run_the_one_verb(hosted, preference):
    hosted.button.click()
    assert preference.shown
    assert hosted.button.isChecked()  # Its face follows the verb it ran.
    hosted.frame.close_button.click()
    assert not preference.shown


def test_the_button_wears_the_panels_reading(hosted):
    assert hosted.button.text() == "(4)"
    hosted.content.reading_changed.emit("(2)")
    assert hosted.button.text() == "(2)"


def test_dispose_reaches_the_content(hosted):
    hosted.dispose()
    assert hosted.content.disposed
