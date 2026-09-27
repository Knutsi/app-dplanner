"""Home: where a window starts — a tab the program opens when nothing else is, the index's
first row, the guide whose buttons are the verbs, and the garden that says what DPlanner does.

Driven through a whole session, because what Home promises is about the window around it:
the program starts on it, a closed last tab leaves the window blank, and the garden moves
only while it is on screen. The garden's rules are plain state, tested without a window.
"""

import pytest
from PySide6.QtWidgets import QCheckBox, QTreeWidget, QTreeWidgetItem
from tests.index_helpers import click, folder

from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, activity_uri, selection_uri
from dplanner.framework.project_list_segment import LeadingRow
from dplanner.modules import start_window
from dplanner.modules.home.garden import CLOUD_LEFT, CLOUD_RIGHT, PLACES, SEEDS, Garden
from dplanner.modules.home.guide import GUIDE
from dplanner.modules.home.module import HomeSegment
from dplanner.modules.home.page import HOME_KIND, GuideRow, HomePage
from dplanner.modules.project_editor.module import PROJECT_KIND
from dplanner.theme.icons import list_icon


@pytest.fixture
def project(services, make_project):
    """One flushed project, so a reload reads it back."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    return project


def home(services) -> HomePage:
    """The Home tab's page, opened (or focused) the way Go ▸ Home does."""
    page = services.tabs.open(HOME_KIND).widget
    assert isinstance(page, HomePage)
    return page


def picked(services, project):
    """The project picked, as a click on its row in the index publishes it."""
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    return services.context.current()


def menu_words(menu) -> list[str]:
    words = [action.text().replace("&", "") for action in menu.actions() if action.text()]
    menu.deleteLater()
    return words


# -- where a window starts ---------------------------------------------------------------------


def test_the_program_starts_on_home_when_nothing_else_is_open(services):
    start_window(services)
    (opened,) = services.tabs.activities()
    assert opened.uri == activity_uri(HOME_KIND)
    assert not services.tabs.is_preview(opened)


def test_a_start_with_tabs_to_reopen_adds_no_home(services, project):
    graph = services.tabs.open(PROJECT_KIND, project.id)
    start_window(services)
    assert services.tabs.activities() == [graph]


def test_closing_the_last_tab_leaves_the_window_blank(services):
    """Home opens at the program's start, never because the tabs ran out."""
    start_window(services)
    for activity in services.tabs.activities():
        services.tabs.close_activity(activity)
    assert services.tabs.activities() == []


def test_home_is_the_top_of_the_index_and_a_click_previews_it(services):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0)
    assert row is folder(panel, "home") and row.text(0) == "Home"
    click(panel, row)
    (home,) = services.tabs.activities()
    assert home.uri == activity_uri(HOME_KIND)
    assert services.tabs.is_preview(home)
    panel.tree.itemActivated.emit(row, 0)
    assert not services.tabs.is_preview(home)


def test_go_seats_home(services):
    services.actions.run("home.open", services.context.current())
    assert [activity.uri for activity in services.tabs.activities()] == [activity_uri(HOME_KIND)]


def test_a_row_hung_under_home_opens_its_surface(services):
    """What another module hangs under Home through ``HomeDeps.rows`` — F10's Control
    Centre — opens like every index row: a click to glance, activation to keep."""
    opened: list[bool] = []
    tree = QTreeWidget()
    root = QTreeWidgetItem(["Home"])
    tree.addTopLevelItem(root)
    homes: list[bool] = []
    row = LeadingRow("Control Centre", list_icon, opened.append)
    segment = HomeSegment(root, homes.append, (row,), services.theme)
    child = root.child(0)
    assert child is not None
    assert child.text(0) == "Control Centre" and not child.icon(0).isNull()
    segment.clicked(child)
    segment.activated(child)
    segment.clicked(root)
    assert opened == [True, False]
    assert homes == [True]
    assert segment.context_menu(child) is None and segment.selection_nodes([child]) == []
    segment.dispose()
    tree.deleteLater()


# -- the index's folders -----------------------------------------------------------------------


def test_the_projects_folder_offers_new_and_open_and_the_tests_folder_nothing(services):
    """The Projects folder renders the File menu's project group, so the index and the menu
    bar cannot disagree about how a project joins the library."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    offered = menu_words(panel.context_menu(folder(panel, "projects")))
    assert offered[:2] == ["New Project…", "Open Project…"]
    assert panel.context_menu(folder(panel, "tests")) is None
    assert panel.context_menu(folder(panel, "home")) is None


# -- the guide ---------------------------------------------------------------------------------


def test_every_verb_the_guide_names_is_registered(services):
    registered = {spec.id for spec in services.actions.all_specs()}
    assert [step.action for step in GUIDE if step.action not in registered] == []


def test_a_guide_verb_greys_with_its_reason_until_a_project_is_picked(services, project):
    page = home(services)
    (row,) = [row for row in page.guide.rows() if row.title.text() == "Talk the steps out"]
    assert isinstance(row, GuideRow)
    assert not row.button.isEnabled()
    assert "no project is open" in row.button.text()

    picked(services, project)
    assert "no project is open" not in row.button.text()


# -- the garden --------------------------------------------------------------------------------


def test_what_the_rain_falls_on_grows_and_nothing_else():
    garden = Garden()
    wet = [index for index in range(len(PLACES)) if garden.rained_on(index)]
    before = list(garden.growth)
    garden.advance(0.5)
    grew = [index for index, grown in enumerate(garden.growth) if grown > before[index]]
    assert wet and grew == wet


def test_a_season_blooms_rests_and_goes_back_to_seed():
    garden = Garden()
    seasons: list[str] = []
    while len(seasons) < 4 and garden.t < 600:
        garden.advance(0.1)
        if not seasons or seasons[-1] != garden.season:
            seasons.append(garden.season)
        if garden.season == "resting":
            assert all(grown == 1.0 for grown in garden.growth)
        assert CLOUD_LEFT - 1e-9 <= garden.cloud_x() <= CLOUD_RIGHT + 1e-9
    assert seasons == ["growing", "resting", "wilting", "growing"]
    assert garden.growth == list(SEEDS)  # Back to seed, never below it.


def test_the_garden_moves_only_while_it_is_on_screen(services, project):
    window = services.window
    window.resize(1000, 700)
    window.show()
    garden = home(services).garden
    assert garden.running()
    services.tabs.open(PROJECT_KIND, project.id)
    assert not garden.running()
    window.hide()


def test_the_garden_paints_every_season(services):
    garden = home(services).garden
    garden.resize(900, garden.height())
    for _ in range(40):
        garden.state.advance(5.0, garden.reach())
        assert not garden.grab().isNull()


def test_the_garden_can_be_put_away_and_brought_back(services):
    page = home(services)
    assert page.garden.isVisibleTo(page)
    page.garden.close_button.click()
    assert not page.garden.isVisibleTo(page)

    (section,) = [s for s in services.settings_sections.sections() if s.id == "home.page"]
    settings = section.factory(None)
    box = settings.findChild(QCheckBox, "GardenBox")
    assert box is not None and not box.isChecked()  # It heard the close.
    box.setChecked(True)
    assert page.garden.isVisibleTo(page)
    settings.deleteLater()
