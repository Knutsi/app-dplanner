"""Projects: the index folder, the verbs, and the tab that shows one.

Actions are tested as pure functions of a constructed ``Context`` — which is the property
that lets the same spec be correct in the menu bar, the palette and the tree's right-click
menu — and behaviour through ``actions.run`` plus ``undo.undo``, so a verb that is not
undoable fails here rather than in front of a user.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import index
from dplanner.modules.projects.index import ProjectEntry, ProjectsSegment


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
    a list of rows cannot show. What may nest under a project is a ProjectEntry — a door
    into a project-scoped surface, not the project's content."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    root = panel.tree.topLevelItem(0)
    assert root.text(0) == "Projects"
    assert root.child(0).text(0) == "Discovery"
    kinds = {
        root.child(0).child(i).data(0, index.KIND_ROLE)
        for i in range(root.child(0).childCount())
    }
    assert "step" not in kinds and kinds <= {"entry"}


def test_the_folder_follows_the_model(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    root = panel.tree.topLevelItem(0)
    AddNodeCommand(services.document.id, Project(title="Build")).redo(services.document)
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["Discovery", "Build"]


def test_selecting_a_row_publishes_the_selection_scope(services, project):
    """The panel publishes once for every segment, so two folders cannot fight over it."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(row)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [selection_uri("project", project.id)]


def test_activating_a_project_folds_rather_than_opens(services, project):
    """A project row is a folder; the graph opens from its Steps entry."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.itemActivated.emit(row, 0)
    assert services.tabs.activities() == []


def test_the_steps_entry_opens_the_project_tab(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    steps = next(
        row.child(i) for i in range(row.childCount()) if row.child(i).text(0) == "Steps"
    )
    panel.tree.itemActivated.emit(steps, 0)
    assert [a.title for a in services.tabs.activities()] == ["Discovery"]


# -- entry rows under a project ----------------------------------------------------------------


@pytest.fixture
def entry_segment(services, project):
    """A ProjectsSegment driven directly, with two stub entries and a record of opens."""
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

    tree = QTreeWidget()
    root = QTreeWidgetItem(["Projects"])
    tree.addTopLevelItem(root)
    opened = []
    segment = ProjectsSegment(
        root=root,
        product=services.document,
        context=services.context,
        actions=services.actions,
        theme=services.theme,
        entries=(
            ProjectEntry(
                id="specs",
                label="Specs",
                open=lambda node_id: opened.append(("specs", node_id)),
                menu="Project",
                order=20,
            ),
            ProjectEntry(
                id="alpha",
                label="Alpha",
                open=lambda node_id: opened.append(("alpha", node_id)),
                order=10,
            ),
        ),
    )
    yield segment, root, opened
    segment.dispose()
    tree.deleteLater()


def test_entries_nest_under_each_project_in_order(entry_segment, project):
    from PySide6.QtCore import Qt

    _segment, root, _opened = entry_segment
    row = root.child(0)
    assert [row.child(i).text(0) for i in range(row.childCount())] == ["Alpha", "Specs"]
    # Expansion keys must be unique per row — the bare project id is the project row's own.
    keys = {row.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(row.childCount())}
    assert keys == {f"{project.id}:alpha", f"{project.id}:specs"}


def test_activating_an_entry_opens_it_for_its_project(entry_segment, project):
    segment, root, opened = entry_segment
    segment.activated(root.child(0))  # The project row itself folds; it opens nothing.
    segment.activated(root.child(0).child(1))
    assert opened == [("specs", project.id)]


def test_an_entry_row_stands_for_its_project_in_the_selection(entry_segment, project):
    """Publishing the project's URI is what keeps the Project verbs live on an entry row —
    and a project selected together with its entry is still one project, not two."""
    segment, root, _opened = entry_segment
    row, entry_row = root.child(0), root.child(0).child(0)
    nodes = segment.selection_nodes([entry_row])
    assert [node.uri for node in nodes] == [selection_uri("project", project.id)]
    nodes = segment.selection_nodes([row, entry_row])
    assert [node.uri for node in nodes] == [selection_uri("project", project.id)]


def test_an_entry_menu_is_the_one_it_names(entry_segment):
    segment, root, _opened = entry_segment
    with_menu, without = root.child(0).child(1), root.child(0).child(0)
    assert segment.context_menu(with_menu) is not None
    assert segment.context_menu(without) is None


def test_a_theme_change_repaints_without_collapsing_expansion(entry_segment, services):
    _segment, root, _opened = entry_segment
    root.child(0).setExpanded(True)
    services.theme.changed.emit(services.theme.current)
    assert root.child(0).isExpanded()
    assert not root.child(0).icon(0).isNull()


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
