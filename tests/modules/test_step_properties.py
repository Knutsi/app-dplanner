"""THE step detail panel: what a host gets, and what it survives.

Every test builds the panel the way a host does — through the module's ``create_panel`` —
because the point of that seam is that a host never constructs the widget itself.
"""

import pytest
from PySide6.QtWidgets import QLabel

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import Project, Step


def module(services):
    return next(m for m in services.modules if m.id == "step_properties")


@pytest.fixture
def project(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(product)
    AddNodeCommand(project.id, Step(title="Draft the model")).redo(product)
    return project


@pytest.fixture
def panel(services, project):
    made = module(services).create_panel(QLabel("nothing selected"))
    yield made
    made.dispose()


def test_a_host_gets_its_own_empty_page(services, panel):
    """Writer parameterises this as a message; a widget is the same idea generalised, and
    it is how a project form gets into a step panel without this module knowing about it."""
    panel.show_step(None)
    assert panel.current_step_id() is None


def test_showing_a_step_reveals_the_aspect_tabs(services, project, panel):
    panel.show_step(project.steps[0].id)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    assert labels == ["Estimate", "Ticket", "Description", "Agent"]


def test_the_title_is_shown_and_edited_undoably(services, project, panel):
    step = project.steps[0]
    panel.show_step(step.id)
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
    panel.show_step(second.id)
    assert "Waits on Read the spec" in panel.links.text()
    panel.show_step(first.id)
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
    panel.show_step(step.id)
    services.undo.push(RemoveNodeCommand(step.id))
    assert panel.current_step_id() is None


def test_a_change_made_elsewhere_reaches_the_title(services, project, panel):
    step = project.steps[0]
    panel.show_step(step.id)
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed elsewhere"))
    assert panel.title_edit.text() == "Renamed elsewhere"


def test_a_disposed_panel_hears_nothing(services, project, panel):
    step = project.steps[0]
    panel.show_step(step.id)
    panel.dispose()
    services.undo.push(SetFieldCommand(step.id, "title", "After disposal"))
    assert panel.title_edit.text() == "Read the spec"
