"""THE step detail panel: what the context puts in it, and what it survives.

Every test reaches the panel the way the application does — one panel, anchored in the
window — because the point of that seam is that nobody constructs a second one.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_properties.module import PANEL_ID


def select(services, *step_ids):
    nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)
    services.context.set_scope(SCOPE_SELECTION, nodes)


@pytest.fixture
def project(services):
    library = services.document
    project = Project(title="Discovery")
    AddNodeCommand(library.id, project).redo(library)
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(library)
    AddNodeCommand(project.id, Step(title="Draft the model")).redo(library)
    return project


@pytest.fixture
def panel(services, project):
    return services.window.dock.widget_for(PANEL_ID)


def test_one_step_selected_is_something_to_edit(services, project, panel):
    """None or several is not — and the panel says so by going off screen rather than by
    showing a placeholder, which is what lets another panel have the area instead."""
    dock = services.window.dock
    select(services, project.steps[0].id)
    assert dock.is_panel_showing(PANEL_ID)
    assert panel.current_step_id() == project.steps[0].id

    select(services, *[step.id for step in project.steps])
    assert not dock.is_panel_showing(PANEL_ID)
    assert panel.current_step_id() is None


def test_showing_a_step_reveals_the_aspect_tabs(services, project, panel):
    select(services, project.steps[0].id)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    expected = ["Estimate", "Ticket", "Description", "Agent", "Release", "Handoff", "GitHub"]
    assert labels == expected


def test_the_title_is_shown_and_edited_undoably(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    assert panel.title_edit.text() == "Read the spec"

    panel.title_edit.setText("Read the whole spec")
    panel.title_edit.editingFinished.emit()
    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"


def test_the_links_line_says_what_a_step_waits_on(services, project, panel):
    from dplanner.domain.commands import SetEdgesCommand

    first, second = project.steps
    SetEdgesCommand(second.id, "requires", [first.id]).redo(services.document)
    select(services, second.id)
    assert "Waits on Read the spec" in panel.links.text()
    select(services, first.id)
    assert "Blocks Draft the model" in panel.links.text()


def test_deselecting_gets_through_the_unchanged_id_gate(services, project, panel):
    """`show_step` early-returns on an unchanged id, but "nothing" has to get through every
    time or the last step stays on screen after the user clicks away."""
    step = project.steps[0]
    panel.show_step(step.id)
    panel.show_step(None)
    assert panel.current_step_id() is None
    panel.show_step(step.id)
    assert panel.current_step_id() == step.id


def test_a_deleted_step_takes_the_panel_back_to_empty(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    services.undo.push(RemoveNodeCommand(step.id))
    assert panel.current_step_id() is None


def test_a_change_made_elsewhere_reaches_the_title(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed elsewhere"))
    assert panel.title_edit.text() == "Renamed elsewhere"


def test_a_disposed_panel_hears_nothing(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    panel.dispose()
    services.undo.push(SetFieldCommand(step.id, "title", "After disposal"))
    assert panel.title_edit.text() == "Read the spec"
