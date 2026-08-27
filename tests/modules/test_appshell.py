"""The shell's tab verbs: what View's Tabs submenu offers, and what each entry does.

Tested as pure functions of a constructed ``Context`` and through ``actions.run``, like every
other verb — which is the property that makes the tab bar's right-click menu correct for
free, since it is the same registry read through the same context.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project

CLOSE_TAB = "appshell.close_tab"
CLOSE_OTHERS = "appshell.close_other_tabs"
CLOSE_RIGHT = "appshell.close_tabs_right"
CLOSE_ALL = "appshell.close_all_tabs"


@pytest.fixture
def projects(services):
    product = services.document
    made = []
    for title in ("Discovery", "Build", "Ship"):
        project = Project(title=title)
        AddNodeCommand(product.id, project).redo(product)
        made.append(project)
    return made


def open_all(services, projects):
    return [services.tabs.open("project", project.id) for project in projects]


def state(services, action_id):
    return services.actions.spec(action_id).state(services.context.current())


def run(services, action_id):
    services.actions.run(action_id, services.context.current())


def titles(services):
    return [activity.title for activity in services.tabs.activities()]


# -- what the menu offers ------------------------------------------------------------------


def test_the_tab_verbs_live_in_the_view_menus_tabs_submenu(services):
    """The placement the tab bar's right-click depends on: show_tab_menu asks build_menu for
    View's Tabs submenu, so a spec that drifts elsewhere silently leaves that popup."""
    for action_id in ("appshell.move_tab_right", "appshell.move_tab_left",
                      CLOSE_TAB, CLOSE_OTHERS, CLOSE_RIGHT, CLOSE_ALL):
        spec = services.actions.spec(action_id)
        assert (spec.menu, spec.group, spec.submenu) == ("View", "tabs", "Tabs")


def test_every_tab_verb_is_off_in_an_empty_window(services):
    """The Tabs submenu is honest about a window with nothing in it rather than offering
    four entries that do nothing."""
    for action_id in (CLOSE_TAB, CLOSE_OTHERS, CLOSE_RIGHT, CLOSE_ALL):
        assert not state(services, action_id).enabled


def test_one_tab_can_be_closed_and_nothing_else(services, projects):
    open_all(services, projects[:1])

    assert state(services, CLOSE_TAB).enabled
    assert state(services, CLOSE_ALL).enabled
    assert not state(services, CLOSE_OTHERS).enabled
    assert not state(services, CLOSE_RIGHT).enabled


# -- what the entries do -------------------------------------------------------------------


def test_close_other_tabs_keeps_the_one_you_are_on(services, projects):
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[1])

    run(services, CLOSE_OTHERS)
    assert titles(services) == ["Build"]


def test_close_tabs_to_the_right_leaves_the_ones_before(services, projects):
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[0])

    assert state(services, CLOSE_RIGHT).enabled
    run(services, CLOSE_RIGHT)
    assert titles(services) == ["Discovery"]


def test_close_tabs_to_the_right_means_this_group(services, projects):
    """ "Right" is a fact about one tab bar. A tab sent to the next group is to the right on
    screen and not in this bar, so it survives."""
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[2])
    services.tabs.move_current_right()
    services.tabs.focus(tabs[0])

    run(services, CLOSE_RIGHT)
    assert sorted(titles(services)) == ["Discovery", "Ship"]


def test_close_all_tabs_empties_the_window(services, projects):
    open_all(services, projects)

    run(services, CLOSE_ALL)
    assert titles(services) == []
    assert services.tabs.current_activity() is None
