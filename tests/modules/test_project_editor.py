"""A project open in a tab: the canvas, the panel beside it, and the gestures between them.

The canvas is exercised through the scene's signals rather than through synthetic mouse
events: what matters is that a gesture becomes the right command on the undo stack, and a
QTest.mousePress would test Qt rather than this module.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetFieldCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION


@pytest.fixture
def project(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    for title in ("Read the spec", "Draft the model"):
        AddNodeCommand(project.id, Step(title=title)).redo(product)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def scene(tab):
    return tab._scene


# -- the canvas ------------------------------------------------------------------------------


def test_the_graph_shows_a_node_per_step(services, project, tab):
    assert set(scene(tab)._nodes) == {step.id for step in project.steps}


def test_a_new_step_appears_without_disturbing_the_others(services, project, tab):
    before = scene(tab)._nodes[project.steps[0].id]
    services.undo.push(AddNodeCommand(project.id, Step(title="Ship it")))
    assert len(scene(tab)._nodes) == 3
    # Node items are reconciled, never rebuilt: one under the mouse must keep its identity.
    assert scene(tab)._nodes[project.steps[0].id] is before


def test_an_edge_is_drawn_for_a_link(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    assert len(scene(tab)._edges) == 1


def test_selecting_a_node_publishes_the_step_and_shows_it(services, project, tab):
    step = project.steps[0]
    scene(tab).select_step(step.id)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [f"app://selection/step/{step.id}"]
    assert tab._panel.current_step_id() == step.id


def test_deselecting_returns_the_panel_to_the_project_form(services, project, tab):
    scene(tab).select_step(project.steps[0].id)
    scene(tab).select_step(None)
    assert tab._panel.current_step_id() is None


# -- gestures become commands -----------------------------------------------------------------


def test_a_drag_is_one_undoable_move(services, project, tab):
    step = project.steps[0]
    scene(tab).nodes_moved.emit([(step.id, 200.0, 120.0)])

    assert services.document.step(step.id).module_data["project_editor"]["x"] == 200.0
    assert services.undo.undo_text() == "Move Step"
    services.undo.undo()
    assert "project_editor" not in services.document.step(step.id).module_data


def test_moving_two_nodes_is_one_undo_step(services, project, tab):
    first, second = project.steps
    scene(tab).nodes_moved.emit([(first.id, 8.0, 8.0), (second.id, 16.0, 16.0)])
    assert services.undo.undo_text() == "Move Steps"
    services.undo.undo()
    assert "project_editor" not in services.document.step(first.id).module_data
    assert "project_editor" not in services.document.step(second.id).module_data


def test_a_link_drop_creates_the_edge(services, project, tab):
    first, second = project.steps
    scene(tab).link_dropped.emit(second.id, first.id)
    assert services.document.step(second.id).edges["requires"] == [first.id]


def test_a_cycle_is_refused_before_the_drop(services, project, tab):
    """The scene asks the model under the cursor, so an illegal drop never happens — there
    is no dialog because there is nothing to apologise for."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    refusal = scene(tab)._link_refusal(first.id, second.id)
    assert refusal is not None and "that is a cycle" in refusal


def test_creating_on_the_canvas_is_one_undo_step(services, project, tab):
    scene(tab).create_requested.emit(240.0, 80.0)
    assert len(project.steps) == 3
    assert project.steps[-1].module_data["project_editor"]["x"] == 240.0
    assert services.undo.undo_text() == "Add Step"
    services.undo.undo()
    assert len(project.steps) == 2


def test_deleting_the_shown_step_leaves_the_panel_empty(services, project, tab, monkeypatch):
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
    step = project.steps[0]
    scene(tab).select_step(step.id)
    scene(tab).delete_requested.emit([step.id])

    assert tab._panel.current_step_id() is None
    assert len(project.steps) == 1


# -- the project form ---------------------------------------------------------------------------


def test_the_project_form_edits_the_project(services, project, tab):
    tab._summary_edit.setText("Replace the index")
    tab._summary_edit.editingFinished.emit()
    assert project.summary == "Replace the index"
    services.undo.undo()
    assert project.summary == ""


def test_a_rename_reaches_the_tab_title(services, project, tab):
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert [a.title for a in services.tabs.activities()] == ["Discovery Phase"]


# -- the rule that keeps opening a tab free -----------------------------------------------------


def test_opening_a_tab_writes_nothing(services, project, tab):
    """Automatic layout is never persisted. If it were, merely opening a project would
    dirty the workspace, and every step an agent created through the CLI would grow a
    position file the next time a window happened to open."""
    services.autosave.flush_now()
    assert not services.autosave.has_pending()
    for step in project.steps:
        assert "project_editor" not in step.module_data
