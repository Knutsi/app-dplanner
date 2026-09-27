"""Home: where a window starts — a tab the program opens when nothing else is, the index's
first row, the guide whose buttons are the verbs, and the tabs kept lately.

Driven through a whole session, because what Home promises is about the window around it:
the program starts on it, a closed last tab leaves the window blank, and a restart keeps what
it lists. A reload is what a restart looks like from inside the process.
"""

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from tests.index_helpers import click, folder

from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, activity_uri, selection_uri
from dplanner.framework.list_rows import DETAIL_ROLE
from dplanner.framework.project_list_segment import LeadingRow
from dplanner.modules import start_window
from dplanner.modules.home.guide import GUIDE
from dplanner.modules.home.module import HomeSegment
from dplanner.modules.home.page import HOME_KIND, NOTHING_RECENT, GuideRow, HomePage
from dplanner.modules.project_editor.module import PROJECT_KIND
from dplanner.modules.spec.activity import SPECS_KIND
from dplanner.modules.step_order.module import ORDER_KIND
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


def listed(page: HomePage) -> list[str]:
    return [page.recent.item(row).text() for row in range(page.recent.count())]


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


# -- the tabs kept lately ----------------------------------------------------------------------


def test_a_kept_tab_is_listed_newest_first_and_a_glance_is_not(services, project):
    page = home(services)
    assert page.empty.text() == NOTHING_RECENT  # Home itself is never listed on Home.
    services.tabs.open(PROJECT_KIND, project.id)
    services.tabs.open(ORDER_KIND, project.id)
    services.tabs.open(SPECS_KIND, project.id, preview=True)
    assert listed(page) == ["Discovery — Order", "Discovery"]

    services.tabs.open(SPECS_KIND, project.id)  # Kept: the preview is pinned where it stands.
    assert listed(page)[0].startswith("Discovery — Specs")
    assert page.empty.text() == ""
    # Under each, when it was last the tab in front: the domain's words for a stamp.
    assert page.recent.item(0).data(DETAIL_ROLE) == "just now"


def test_the_home_tab_is_not_listed_on_itself(services, project):
    services.tabs.open(PROJECT_KIND, project.id)
    home = services.tabs.open(HOME_KIND)
    assert listed(home.widget) == ["Discovery"]


def test_what_was_kept_survives_a_restart(session, services, project):
    services.tabs.open(ORDER_KIND, project.id)
    services.tabs.open(PROJECT_KIND, project.id)
    for activity in services.tabs.activities():
        services.tabs.close_activity(activity)
    assert session.reload()
    assert listed(home(session.services)) == ["Discovery", "Discovery — Order"]


def test_a_project_that_leaves_the_library_leaves_the_list(services, project, monkeypatch):
    from dplanner.modules.projects import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args, **_kwargs: True)
    page = home(services)
    services.tabs.open(PROJECT_KIND, project.id)
    services.actions.run("projects.remove", picked(services, project))
    assert listed(page) == []
    assert page.empty.text() == NOTHING_RECENT


def test_a_recent_tab_reopens_with_one_click(services, project):
    services.tabs.close_activity(services.tabs.open(PROJECT_KIND, project.id))
    page = home(services)
    page.recent.itemClicked.emit(page.recent.item(0))
    current = services.tabs.current_activity()
    assert current is not None and current.uri == activity_uri(PROJECT_KIND, project.id)


def test_the_second_click_of_a_double_click_does_not_land_on_what_opened(services, project):
    """The row swaps Home away under the pointer, and Qt hands the habitual second click to
    whatever replaced it as a double-click — on empty canvas, a new step. That one
    double-click is dropped; the next one is the person's own."""
    window = services.window
    window.resize(1000, 700)
    window.show()
    services.tabs.close_activity(services.tabs.open(PROJECT_KIND, project.id))
    page = home(services)
    page.recent.itemClicked.emit(page.recent.item(0))
    QApplication.processEvents()
    graph = services.tabs.current_activity()
    canvas = graph._view.viewport()
    heard = _DoubleClicks()
    canvas.installEventFilter(heard)
    pos = QPointF(canvas.mapTo(window, canvas.rect().center()))

    def double_click() -> None:
        QApplication.sendEvent(
            window.windowHandle(),
            QMouseEvent(
                QEvent.Type.MouseButtonDblClick,
                pos,
                QPointF(window.mapToGlobal(pos.toPoint())),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    double_click()
    assert heard.count == 0
    double_click()
    assert heard.count == 1
    canvas.removeEventFilter(heard)
    window.hide()


class _DoubleClicks(QObject):
    """Counts the double-clicks that reach a widget, and keeps them from it."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self.count += 1
            return True
        return super().eventFilter(watched, event)
