"""The panel dock: where a panel goes, and what puts it on screen.

Every test builds a dock standalone — no window, no session — because that is what it
promises it can be, and because "is this panel showing" is then a question with one answer
rather than one that depends on whether a window was ever raised.
"""

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    selection_uri,
)
from dplanner.framework.panels import (
    AREA_DEFAULT_SIZE,
    PanelArea,
    PanelDock,
    PanelRegistry,
    PanelSpec,
    _stored_collapsed,
)


class FakeContextPanel(QWidget):
    """Shows itself only while a thing of its kind is selected."""

    def __init__(self, kind="thing"):
        super().__init__()
        self._kind = kind
        self.target = None

    def show_context(self, context: Context) -> bool:
        self.target = context.selected_entity(self._kind)
        return self.target is not None

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def context():
    return ContextService()


@pytest.fixture
def registry():
    return PanelRegistry()


@pytest.fixture
def dock(app, registry, context):
    made = PanelDock(registry, context, QLabel("the tabs"))
    made.resize(1200, 800)  # A real width, so the areas get their stored sizes rather than a ratio.
    yield made
    made.dispose()


def spec(panel_id, factory=QWidget, area=PanelArea.RIGHT, order=50):
    return PanelSpec(id=panel_id, title=panel_id.title(), factory=factory, area=area, order=order)


def select(context, kind, *ids):
    context.set_scope(SCOPE_SELECTION, tuple(ContextNode(selection_uri(kind, one)) for one in ids))


# -- where a panel goes --------------------------------------------------------------------------


def test_a_panel_registered_later_still_arrives(dock, registry):
    """Every module registers after the dock is built, so this is the ordinary case."""
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.area_of("index") is PanelArea.LEFT
    assert dock.is_panel_showing("index")


def test_a_panel_with_no_context_opinion_is_simply_shown(dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.is_panel_showing("index")


def test_moving_a_panel_changes_its_area_and_is_remembered(dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.move_panel("index", PanelArea.BOTTOM)
    assert dock.area_of("index") is PanelArea.BOTTOM
    assert QSettings().value("layout/panels/index/area") == PanelArea.BOTTOM.value


def test_a_remembered_area_beats_the_spec(app, context):
    QSettings().setValue("layout/panels/index/area", PanelArea.RIGHT.value)
    registry = PanelRegistry()
    dock = PanelDock(registry, context, QLabel())
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.area_of("index") is PanelArea.RIGHT
    dock.dispose()


def test_an_area_the_build_no_longer_has_falls_back_to_the_spec(app, context):
    QSettings().setValue("layout/panels/index/area", "starboard")
    registry = PanelRegistry()
    dock = PanelDock(registry, context, QLabel())
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.area_of("index") is PanelArea.LEFT
    dock.dispose()


# -- what puts one on screen ---------------------------------------------------------------------


def test_a_panel_with_nothing_to_show_goes_off_screen(dock, registry, context):
    panel = FakeContextPanel()
    registry.register(spec("detail", factory=lambda: panel))
    assert not dock.is_panel_showing("detail")

    select(context, "thing", "one")
    assert dock.is_panel_showing("detail")
    assert panel.target == "one"

    select(context, "thing")
    assert not dock.is_panel_showing("detail")


def test_two_panels_in_one_area_take_turns_without_knowing_it(dock, registry, context):
    """The whole arrangement the right side relies on: each answers about the context, and
    neither has ever heard of the other."""
    steps = FakeContextPanel("step")
    projects = FakeContextPanel("project")
    registry.register(spec("step", factory=lambda: steps, order=20))
    registry.register(spec("project", factory=lambda: projects, order=10))

    select(context, "step", "s1")
    assert dock.is_panel_showing("step") and not dock.is_panel_showing("project")
    select(context, "project", "p1")
    assert dock.is_panel_showing("project") and not dock.is_panel_showing("step")


def test_hiding_a_panel_survives_something_to_show(dock, registry, context):
    panel = FakeContextPanel()
    registry.register(spec("detail", factory=lambda: panel))
    dock.set_panel_visible("detail", False)
    select(context, "thing", "one")
    assert not dock.is_panel_showing("detail")
    assert not dock.is_panel_visible("detail")

    dock.set_panel_visible("detail", True)
    assert dock.is_panel_showing("detail")


def test_a_hidden_panel_is_remembered(app, context):
    QSettings().setValue("layout/panels/index/hidden", True)
    registry = PanelRegistry()
    dock = PanelDock(registry, context, QLabel())
    registry.register(spec("index", area=PanelArea.LEFT))
    assert not dock.is_panel_visible("index")
    dock.dispose()


def test_moving_and_hiding_announce_themselves(dock, registry):
    """What View ▸ Panels re-reads its checkmarks from — the menu is not the only way in."""
    heard: list[str] = []
    dock.panels_changed.connect(heard.append)
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_panel_visible("index", False)
    dock.move_panel("index", PanelArea.RIGHT)
    assert heard == ["index", "index"]


# -- collapsing an area --------------------------------------------------------------------------


def test_collapsing_an_area_takes_its_panels_off_screen_but_not_switched_off(dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_area_collapsed(PanelArea.LEFT, True)

    assert dock.is_area_collapsed(PanelArea.LEFT)
    assert not dock.is_panel_showing("index")
    # Still switched on — collapse folds the side away, it does not hide the panel.
    assert dock.is_panel_visible("index")
    assert dock.sizes()[0] == 0


def test_expanding_restores_the_size(dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_area_collapsed(PanelArea.LEFT, True)
    dock.set_area_collapsed(PanelArea.LEFT, False)
    assert dock.is_panel_showing("index")
    assert dock.sizes()[0] == AREA_DEFAULT_SIZE[PanelArea.LEFT]


def test_a_collapsed_area_is_remembered(app, context):
    QSettings().setValue("layout/areas/left/collapsed", True)
    registry = PanelRegistry()
    dock = PanelDock(registry, context, QLabel())
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.is_area_collapsed(PanelArea.LEFT)
    assert not dock.is_panel_showing("index")

    dock.set_area_collapsed(PanelArea.LEFT, False)
    assert not _stored_collapsed(PanelArea.LEFT)
    dock.dispose()


def test_a_collapsed_area_never_persists_a_zero_size(dock, registry):
    """The splitterMoved handler must not remember the 0 the collapse produced — expanding
    has to bring back the width the user last dragged to."""
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_area_collapsed(PanelArea.LEFT, True)
    dock._persist_outer(0, 1)
    assert dock._sizes[PanelArea.LEFT] == AREA_DEFAULT_SIZE[PanelArea.LEFT]
    assert QSettings().value("layout/areas/left") is None


def test_something_to_show_does_not_expand_a_collapsed_area(dock, registry, context):
    """Collapse is the user's choice and survives selection changes — the whole point of it
    being separate from a panel's own has-content answer."""
    panel = FakeContextPanel()
    registry.register(spec("detail", factory=lambda: panel))
    dock.set_area_collapsed(PanelArea.RIGHT, True)
    select(context, "thing", "one")
    assert not dock.is_panel_showing("detail")
    assert dock.is_area_collapsed(PanelArea.RIGHT)


def test_switching_a_panel_on_expands_its_collapsed_area(dock, registry):
    """A checkmark that turns on with nothing appearing reads as a bug."""
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_panel_visible("index", False)
    dock.set_area_collapsed(PanelArea.LEFT, True)

    dock.set_panel_visible("index", True)
    assert not dock.is_area_collapsed(PanelArea.LEFT)
    assert dock.is_panel_showing("index")


def test_moving_a_panel_into_a_collapsed_area_expands_it(dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    dock.set_area_collapsed(PanelArea.RIGHT, True)

    dock.move_panel("index", PanelArea.RIGHT)
    assert not dock.is_area_collapsed(PanelArea.RIGHT)
    assert dock.is_panel_showing("index")


def test_collapsing_announces_itself(dock, registry):
    """What the View menu's side-panel checkmarks re-read from — including when a gesture
    expands the area rather than the toggle."""
    heard: list[PanelArea] = []
    dock.areas_changed.connect(heard.append)
    registry.register(spec("index", area=PanelArea.LEFT))

    dock.set_area_collapsed(PanelArea.LEFT, True)
    dock.set_area_collapsed(PanelArea.LEFT, True)  # Already collapsed: no echo.
    dock.set_panel_visible("index", True)  # The reveal path expands, so it announces too.
    assert heard == [PanelArea.LEFT, PanelArea.LEFT]


# -- sizing ----------------------------------------------------------------------------------------


def test_an_area_with_nothing_in_it_takes_no_space(dock, registry, context):
    """An empty right side is a wider canvas, not a blank column."""
    registry.register(spec("detail", factory=FakeContextPanel))
    assert dock.sizes()[2] == 0

    select(context, "thing", "one")
    assert dock.sizes()[2] == AREA_DEFAULT_SIZE[PanelArea.RIGHT]


def test_a_stored_size_is_clamped(app, context):
    QSettings().setValue("layout/areas/left", 5000)
    registry = PanelRegistry()
    dock = PanelDock(registry, context, QLabel())
    dock.resize(1200, 800)
    registry.register(spec("index", area=PanelArea.LEFT))
    assert dock.sizes()[0] <= 600
    dock.dispose()


def test_disposing_reaches_every_context_panel(dock, registry):
    panel = FakeContextPanel()
    registry.register(spec("detail", factory=lambda: panel))
    dock.dispose()
    assert panel.disposed


# -- the header, which is how a panel is moved ------------------------------------------------


def test_a_right_click_on_the_header_asks_the_dock_for_a_menu(app, dock, registry, monkeypatch):
    """The affordance the whole arrangement rests on: the content widget keeps its own
    context menu (the index tree has one), so the header is what is left to point at. The
    label does not consume the event, so it propagates to the frame the dock listens to."""
    registry.register(spec("index", area=PanelArea.LEFT))
    asked: list[str] = []
    monkeypatch.setattr(dock, "_show_menu", lambda panel_id, _position: asked.append(panel_id))
    QApplication.sendEvent(
        dock._frames["index"].header,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)),
    )
    assert asked == ["index"]


def test_the_header_menu_offers_the_areas_it_is_not_in(app, dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    menu = dock._panel_menu("index")
    entries = {a.text(): (a.isEnabled(), a.isChecked()) for a in menu.actions()}

    assert entries["Move to &Left"] == (False, True)  # Where it already is.
    assert entries["Move to &Right"] == (True, False)
    assert entries["Move to &Bottom"] == (True, False)
    assert "&Hide Panel" in entries


def test_the_menu_actually_moves_the_panel(app, dock, registry):
    registry.register(spec("index", area=PanelArea.LEFT))
    menu = dock._panel_menu("index")
    next(a for a in menu.actions() if a.text() == "Move to &Bottom").trigger()
    assert dock.area_of("index") is PanelArea.BOTTOM
