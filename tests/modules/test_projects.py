"""Projects: the index folder, the verbs, and the tab that shows one.

Actions are tested as pure functions of a constructed ``Context`` — which is the property
that lets the same spec be correct in the menu bar, the palette and the tree's right-click
menu — and behaviour through ``actions.run`` plus ``undo.undo``, so a verb that is not
undoable fails here rather than in front of a user.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri


@pytest.fixture
def project(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(product)
    return project


def select(services, kind, node_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri(kind, node_id)),))
    return services.context.current()


def state(services, action_id, context):
    return services.actions.spec(action_id).state(context)


# -- the index folder --------------------------------------------------------------------------


def test_the_module_contributes_one_index_folder(services):
    assert [segment.id for segment in services.index_segments.segments()] == ["projects"]


def test_the_folder_shows_projects_and_not_their_steps(services, project):
    """Steps left the index when the graph arrived: a step is a position in a graph, which
    a list of rows cannot show."""
    panel = services.window.sidebar()
    root = panel.tree.topLevelItem(0)
    assert root.text(0) == "Projects"
    assert root.child(0).text(0) == "Discovery"
    assert root.child(0).childCount() == 0


def test_the_folder_follows_the_model(services, project):
    panel = services.window.sidebar()
    root = panel.tree.topLevelItem(0)
    AddNodeCommand(services.document.id, Project(title="Build")).redo(services.document)
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["Discovery", "Build"]


def test_selecting_a_row_publishes_the_selection_scope(services, project):
    """The panel publishes once for every segment, so two folders cannot fight over it."""
    panel = services.window.sidebar()
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(row)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [selection_uri("project", project.id)]


def test_activating_a_project_opens_its_tab(services, project):
    panel = services.window.sidebar()
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.itemActivated.emit(row, 0)
    assert [a.title for a in services.tabs.activities()] == ["Discovery"]


# -- the verbs ---------------------------------------------------------------------------------


def test_project_verbs_hide_without_a_project(services):
    context = services.context.current()
    for action_id in ("projects.rename", "projects.delete", "projects.open"):
        assert not state(services, action_id, context).visible
    assert state(services, "projects.new", context).enabled


def test_project_verbs_enable_on_a_selected_project(services, project):
    context = select(services, "project", project.id)
    for action_id in ("projects.rename", "projects.delete", "projects.open"):
        assert state(services, action_id, context).enabled


def test_new_project_is_created_and_undone(services, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Build", True))
    services.actions.run("projects.new", services.context.current())
    assert [p.title for p in services.document.projects] == ["Build"]

    services.undo.undo()
    assert services.document.projects == []


def test_delete_takes_the_project_and_its_tab(services, project, monkeypatch):
    from dplanner.modules.projects import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *a, **k: True)
    services.tabs.open("project", project.id)
    assert services.tabs.activities()

    services.actions.run("projects.delete", select(services, "project", project.id))
    assert services.document.projects == []
    assert services.tabs.activities() == []


def test_rename_reaches_the_tab_title(services, project, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    services.tabs.open("project", project.id)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Discovery Phase", True))
    services.actions.run("projects.rename", select(services, "project", project.id))
    assert [a.title for a in services.tabs.activities()] == ["Discovery Phase"]
