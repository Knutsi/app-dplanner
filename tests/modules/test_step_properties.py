"""THE step detail panel: what the context puts in it, and what it survives.

Every test reaches the panel the way the application does — one panel, anchored in the
window — because the point of that seam is that no *surface* constructs a second one. The
details dialog is the sanctioned exception: a transient second host of the same sections,
opened by the ``steps.details`` verb and disposed when it closes.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_properties.module import PANEL_ID


def select(services, *step_ids):
    nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)
    services.context.set_scope(SCOPE_SELECTION, nodes)


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
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


# -- the details dialog ----------------------------------------------------------------------


def test_details_needs_exactly_one_selected_step(services, project):
    """Disabled, never hidden: none or several selected teaches the precondition."""
    spec = services.actions.spec("steps.details")
    select(services)
    assert not spec.state(services.context.current()).enabled
    select(services, *[step.id for step in project.steps])
    assert not spec.state(services.context.current()).enabled
    select(services, project.steps[0].id)
    assert spec.state(services.context.current()).enabled


def test_details_opens_a_dialog_that_is_the_panel_and_disposes_it(
    services, project, monkeypatch
):
    """The dialog hosts a second StepPanel over the same sections — 1:1 with the anchored
    one by construction — and stops hearing the model once closed."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    (dialog,) = opened
    assert dialog.panel.current_step_id() == step.id
    assert dialog.panel.tab_bar.count() > 0  # The aspect tabs arrived.
    # exec() returned, so run() has already disposed it: a model change must not reach it.
    services.undo.push(SetFieldCommand(step.id, "title", "After closing"))
    assert dialog.panel.title_edit.text() == "Read the spec"


def test_an_edit_in_the_dialog_lands_on_the_undo_stack(services, project, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]

    def edit_title(dialog):
        dialog.panel.title_edit.setText("Read the whole spec")
        dialog.panel.title_edit.editingFinished.emit()

    monkeypatch.setattr(StepDetailsDialog, "exec", edit_title)
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"
