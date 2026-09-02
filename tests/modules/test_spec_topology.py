"""The Specs tab's pinned first row: the topology, edited in place."""

import pytest

from dplanner.domain.model import TextEdit
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.list_rows import DETAIL_ROLE
from dplanner.modules.spec.activity import NAME_ROLE, TOPOLOGY_ROW, SpecsActivity
from dplanner.modules.spec.aspect import MODULE_ID, read_topology


@pytest.fixture
def project(make_project):
    return make_project("Discovery")


@pytest.fixture
def activity(services, project):
    activity = services.tabs.open("specs", project.id)
    assert isinstance(activity, SpecsActivity)
    return activity


def test_the_topology_is_the_first_row_and_shows_its_editor(services, project, activity):
    first = activity.list.item(0)
    assert first.text() == "Topology" and first.data(NAME_ROLE) == TOPOLOGY_ROW
    assert first.data(DETAIL_ROLE) == "not written yet"
    assert activity.list.currentRow() == 0
    assert activity._views.currentWidget() is activity._topology_page


def test_typing_writes_the_projects_prose_through_the_undo_stack(services, project, activity):
    activity.topology.edit.setFocus()
    activity.topology.edit.insertPlainText("Views are features.")
    assert read_topology(project) == "Views are features."
    assert activity.list.item(0).data(DETAIL_ROLE) == "how this project's graph is shaped"
    services.undo.undo()
    assert read_topology(project) == ""


def test_a_foreign_edit_reaches_the_editor(services, project, activity):
    from dplanner.domain.commands import EditTextCommand

    services.undo.push(
        EditTextCommand(TextEdit(project.id, MODULE_ID, 0, "", "From the CLI."), label="Set")
    )
    assert activity.topology.edit.toPlainText() == "From the CLI."


def test_the_topology_row_selects_no_document(services, project, activity):
    """Remove and Open Externally act on documents; the topology is not one."""
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    activity.list.setCurrentRow(0)
    activity.on_activated()
    context = services.context.current()
    assert context.selected_entity("spec_document") is None
    assert not services.actions.spec("spec.remove").state(context).enabled
    assert not services.actions.spec("spec.edit").state(context).enabled
