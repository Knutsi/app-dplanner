"""The Specs tab's pinned first row: the topology, edited in place."""

import pytest

from dplanner.domain.model import TextEdit
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.list_rows import DETAIL_ROLE, EMPHASIS_ROLE, RULE_ROLE
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
    first = activity.row_item(0)
    assert first.text(0) == "Topology" and first.data(0, NAME_ROLE) == TOPOLOGY_ROW
    assert first.data(0, DETAIL_ROLE) == "not written yet"
    # Not one more document: the graph's glyph, a bold name, a rule under the row.
    assert not first.icon(0).isNull()
    assert first.data(0, EMPHASIS_ROLE) is True and first.data(0, RULE_ROLE) is True
    assert activity.current_row() == 0
    assert activity._views.currentWidget() is activity._topology_page


def test_typing_writes_the_projects_prose_through_the_undo_stack(services, project, activity):
    activity.topology.edit.setFocus()
    activity.topology.edit.insertPlainText("Views are features.")
    assert read_topology(project) == "Views are features."
    assert activity.row_item(0).data(0, DETAIL_ROLE) == "how this project's graph is shaped"
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
    activity.select_row(0)
    activity.on_activated()
    context = services.context.current()
    assert context.selected_entity("spec_document") is None
    assert not services.actions.spec("spec.remove").state(context).enabled


def test_the_default_shape_stands_under_the_editor(services, project, activity):
    """One asset, two surfaces: the person writing the topology reads what the agent is
    handed, so the two can never be looking at different documents."""
    from dplanner.cli.shaping import guide

    services.tabs.open("specs", project.id)
    shown = activity.default_shape.toPlainText()
    assert "How a graph is shaped" in shown
    assert "Project start" in shown
    assert shown.strip().startswith(guide().split("\n", 1)[0].lstrip("# ").strip())


def test_the_default_can_be_shut_and_draws_no_edge_of_its_own(services, project, activity):
    """A splitter, so somebody who has read it once gets the room back — and the seam is
    the splitter's, from the one QSplitter::handle rule (DESIGN.md's *Seams*)."""
    from PySide6.QtWidgets import QSplitter

    split = activity.default_shape.parent().parent()
    assert isinstance(split, QSplitter)
    assert split.childrenCollapsible()
    assert activity.default_shape.frameShape() == activity.default_shape.Shape.NoFrame
