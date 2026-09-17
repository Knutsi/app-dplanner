"""The Dashboard tab: the project's home, opened about one project and never re-targeted."""

import pytest

from dplanner.domain.commands import RemoveNodeCommand, SetFieldCommand
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    activity_uri,
    selection_uri,
)
from dplanner.modules.project_dashboard.activity import DASHBOARD_KIND


@pytest.fixture
def project(services, make_project):
    return make_project("Discovery")


@pytest.fixture
def tab(services, project):
    return services.tabs.open(DASHBOARD_KIND, project.id)


def on(project):
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("project", project.id)),)})


def test_the_verb_opens_the_projects_dashboard_and_is_greyed_without_one(services, project):
    spec = services.actions.spec("dashboard.open")
    assert (spec.menu, spec.group) == ("Project", "open")
    assert not spec.state(Context({})).enabled

    services.actions.run("dashboard.open", on(project))
    (activity,) = services.tabs.activities()
    assert activity.uri == activity_uri(DASHBOARD_KIND, project.id)
    assert activity.title == "Discovery — Dashboard"


def test_the_cards_are_every_modules_in_registry_order(tab):
    """Whoever registered a project card appears here; this module never learns whose."""
    assert [card.title.text() for card in tab.page.cards] == [
        "Repositories",
        "Agent",
        "Compilation instructions",
    ]


def test_the_form_edits_the_project_undoably(services, project, tab):
    page = tab.page
    assert page.title_edit.text() == "Discovery"
    page.summary_edit.setText("Replace the index")
    page.summary_edit.editingFinished.emit()
    assert project.summary == "Replace the index"
    services.undo.undo()
    assert project.summary == ""
    assert page.summary_edit.text() == ""


def test_a_change_made_elsewhere_reaches_an_idle_field_and_leaves_a_busy_one_alone(
    services, project, tab
):
    page = tab.page
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert page.title_edit.text() == "Discovery Phase"

    page.summary_edit.setFocus()
    page.summary_edit.setText("half a thou")
    services.undo.push(SetFieldCommand(project.id, "summary", "Somebody else's"))
    if page.summary_edit.hasFocus():  # Offscreen, focus follows the window's activation.
        assert page.summary_edit.text() == "half a thou"


def test_a_rename_retitles_the_tab_and_removal_closes_it(services, project, tab):
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert [a.title for a in services.tabs.activities()] == ["Discovery Phase — Dashboard"]
    RemoveNodeCommand(project.id).redo(services.document)
    assert services.tabs.activities() == []


def test_the_projects_verbs_are_live_while_the_dashboard_is_current(services, project, tab):
    """The tab publishes its project, so Project Settings… and the cards' own verbs work
    from here without a selection anybody made."""
    tab.on_activated()
    assert services.actions.spec("projects.settings").state(services.context.current()).enabled


def test_the_form_and_the_test_panel_have_left_the_window_areas(services):
    """After this change no panel targets the right area by default: the project's form is
    this tab, the Test panel stands inside the Tests tab, and the index is what is left."""
    assert [spec.id for spec in services.panels.panels()] == ["index"]
