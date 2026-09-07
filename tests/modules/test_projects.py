"""Projects: the index folder, the verbs, and the tab that shows one.

Actions are tested as pure functions of a constructed ``Context`` — which is the property
that lets the same spec be correct in the menu bar, the palette and the tree's right-click
menu — and behaviour through ``actions.run`` plus ``undo.undo``, so a verb that is not
undoable fails here rather than in front of a user.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import index
from dplanner.modules.projects.index import ProjectEntry, ProjectsSegment


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    return project


def select(services, kind, node_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri(kind, node_id)),))
    return services.context.current()


def state(services, action_id, context):
    return services.actions.spec(action_id).state(context)


# -- the index folder --------------------------------------------------------------------------


def test_the_module_contributes_the_first_index_folder(services):
    """Projects is the top folder; Tests registers below it. Order is (order, id)."""
    assert [segment.id for segment in services.index_segments.segments()] == [
        "projects",
        "tests",
        "docs",
    ]


def test_the_folder_shows_projects_and_not_their_steps(services, project):
    """Steps left the index when the graph arrived: a step is a position in a graph, which
    a list of rows cannot show. What may nest under a project is a ProjectEntry — a door
    into a project-scoped surface, not the project's content."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    root = panel.tree.topLevelItem(0)
    assert root.text(0) == "Projects"
    assert root.child(0).text(0) == "Discovery"
    kinds = {
        root.child(0).child(i).data(0, index.KIND_ROLE) for i in range(root.child(0).childCount())
    }
    assert "step" not in kinds and kinds <= {"entry"}


def test_the_folder_follows_the_model(services, project, make_project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    root = panel.tree.topLevelItem(0)
    make_project("Build")
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["Discovery", "Build"]


def test_selecting_a_row_publishes_the_selection_scope(services, project):
    """The panel publishes once for every segment, so two folders cannot fight over it."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(row)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [selection_uri("project", project.id)]


def test_a_rebuild_keeps_the_tree_selection_and_the_published_scope(services, project):
    """A rename anywhere rebuilds the folder; the rebuild used to drop the tree's
    selection, publish an empty scope, and take the detail panel off what the user was
    looking at."""
    from dplanner.domain.commands import SetFieldCommand

    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(row)

    SetFieldCommand(project.id, "title", "Renamed").redo(services.document)
    fresh_row = panel.tree.topLevelItem(0).child(0)
    assert fresh_row.isSelected()
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [selection_uri("project", project.id)]


def test_a_rebuild_that_loses_the_selected_row_announces_the_empty_selection(services, project):
    """The other half of the rule: a selected project actually deleted must clear the
    published scope rather than leave panels pointing at a ghost."""
    from dplanner.domain.commands import RemoveNodeCommand

    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(row)

    RemoveNodeCommand(project.id).redo(services.document)
    assert services.context.current().scope(SCOPE_SELECTION) == ()


def test_activating_a_project_folds_rather_than_opens(services, project):
    """A project row is a folder; the graph opens from its Steps entry."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    panel.tree.itemActivated.emit(row, 0)
    assert services.tabs.activities() == []


def test_the_steps_entry_opens_the_project_tab(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    steps = next(row.child(i) for i in range(row.childCount()) if row.child(i).text(0) == "Steps")
    panel.tree.itemActivated.emit(steps, 0)
    assert [a.title for a in services.tabs.activities()] == ["Discovery"]


# -- single-click previews ---------------------------------------------------------------------


def click(panel, item, modifiers=None, button=None):
    """A plain click on a row, as press-then-release through the panel's event filter.

    Hand-built events rather than QTest.mouseClick: QTest drives the QPA layer, whose
    button bookkeeping leaks into ``QApplication.mouseButtons()`` for later tests.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    modifiers = Qt.KeyboardModifier.NoModifier if modifiers is None else modifiers
    button = Qt.MouseButton.LeftButton if button is None else button
    viewport = panel.tree.viewport()
    pos = QPointF(panel.tree.visualItemRect(item).center())
    for kind, held in (
        (QEvent.Type.MouseButtonPress, button),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            viewport,
            QMouseEvent(
                kind, pos, QPointF(viewport.mapToGlobal(pos.toPoint())), button, held, modifiers
            ),
        )


def entry_row(panel, label):
    row = panel.tree.topLevelItem(0).child(0)
    return next(row.child(i) for i in range(row.childCount()) if row.child(i).text(0) == label)


def test_clicking_an_entry_opens_it_as_a_preview(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    panel.tree.expandAll()
    click(panel, entry_row(panel, "Steps"))

    (tab,) = services.tabs.activities()
    assert tab.title == "Discovery"
    assert services.tabs.is_preview(tab)


def test_activating_after_the_click_pins_the_preview(services, project):
    """The double-click sequence: the first click previews, the activation keeps it."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    panel.tree.expandAll()
    steps = entry_row(panel, "Steps")
    click(panel, steps)
    panel.tree.itemActivated.emit(steps, 0)

    (tab,) = services.tabs.activities()
    assert not services.tabs.is_preview(tab)


def test_the_next_click_replaces_the_preview(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    panel.tree.expandAll()
    click(panel, entry_row(panel, "Steps"))
    click(panel, entry_row(panel, "Progression"))

    (tab,) = services.tabs.activities()
    assert "Progression" in tab.title
    assert services.tabs.is_preview(tab)


def test_a_modified_click_builds_a_selection_and_previews_nothing(services, project):
    from PySide6.QtCore import Qt

    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    panel.tree.expandAll()
    click(panel, entry_row(panel, "Steps"), modifiers=Qt.KeyboardModifier.ControlModifier)
    assert services.tabs.activities() == []


def test_clicking_a_project_row_previews_nothing(services, project):
    """A project row is a folder: a click selects it, and that is the whole gesture."""
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    panel.tree.expandAll()
    click(panel, panel.tree.topLevelItem(0).child(0))
    assert services.tabs.activities() == []


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
        library=services.document,
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


def test_a_problem_entry_is_a_greyed_row_that_selects_nothing(services, project):
    """A library entry that could not open is still the user's project: it shows greyed
    with the reason, cannot be activated into anything, and never enters the selection."""
    from pathlib import Path

    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

    from dplanner.domain.store import ProjectProblem

    tree = QTreeWidget()
    root = QTreeWidgetItem(["Projects"])
    tree.addTopLevelItem(root)
    problem = ProjectProblem(Path("/gone/search-rewrite"), "no project.dproj here")
    segment = ProjectsSegment(
        root=root,
        library=services.document,
        context=services.context,
        actions=services.actions,
        theme=services.theme,
        problems=lambda: [problem],
    )
    try:
        row = root.child(root.childCount() - 1)
        assert row is not None
        assert row.text(0) == "search-rewrite — unavailable"
        assert row.isDisabled()
        assert row.data(0, index.KIND_ROLE) == "problem"
        assert "no project.dproj here" in row.toolTip(0)
        assert segment.selection_nodes([row]) == []
        assert segment.context_menu(row) is None
    finally:
        segment.dispose()
        tree.deleteLater()


# -- the verbs ---------------------------------------------------------------------------------


def test_project_verbs_grey_without_a_project(services):
    context = services.context.current()
    for action_id in ("projects.settings", "projects.move", "projects.remove", "projects.open"):
        found = state(services, action_id, context)
        assert found.visible and not found.enabled


def test_project_verbs_enable_on_a_selected_project(services, project):
    context = select(services, "project", project.id)
    for action_id in ("projects.settings", "projects.move", "projects.remove", "projects.open"):
        assert state(services, action_id, context).enabled


def test_remove_takes_the_project_out_of_model_and_store_but_leaves_its_files(
    services, project, monkeypatch
):
    """Removal is from the library only: the model forgets it, the store forgets it, the
    tab goes, and the directory stays exactly where it was — which is what the confirm
    prompt promises."""
    from dplanner.domain.store import PROJECT_META
    from dplanner.modules.projects import verbs

    asked = []

    def fake_confirm(_parent, title, question):
        asked.append((title, question))
        return True

    monkeypatch.setattr(verbs, "confirm", fake_confirm)
    directory = services.repo.project_dir(project.id)
    services.tabs.open("project", project.id)
    assert services.tabs.activities()

    services.actions.run("projects.remove", select(services, "project", project.id))
    assert services.document.projects == []
    assert services.tabs.activities() == []
    with pytest.raises(KeyError):  # Detached: the store no longer tracks the directory.
        services.repo.project_dir(project.id)
    assert asked[0][0] == "Remove from Library"
    assert "files stay" in asked[0][1]
    assert (directory / PROJECT_META).is_file()  # The files really did stay.


def test_move_plan_stays_offered_once_the_plan_has_its_own_repository(services, project, tmp_path):
    """Move Plan is not a one-time migration out of the code: a plan repository picked
    wrongly is put right from the same verb, so it never stands down on a project."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.commands import SetFieldCommand

    context = select(services, "project", project.id)
    assert state(services, "projects.move", context).enabled
    services.undo.push(SetFieldCommand(project.id, "repository", "https://github.com/acme/widget"))
    services.repo.set_checkout(project.id, init_repo(tmp_path / "widget"))
    assert state(services, "projects.move", context).enabled


def test_a_rename_in_the_project_dialog_reaches_the_tab_title_through_undo(services, project):
    """Settings… replaces Rename: the name is a live field of the Project dialog, one
    instance per window, and the write is the same undoable command."""
    module = next(m for m in services.modules if m.id == "projects")
    services.tabs.open("project", project.id)
    services.actions.run("projects.settings", select(services, "project", project.id))
    dialog = module._dialog
    assert dialog is not None and dialog.isVisible() and dialog.project_id() == project.id
    services.actions.run("projects.settings", select(services, "project", project.id))
    assert module._dialog is dialog  # Re-aimed, never a second one.

    dialog.name_edit.setText("Discovery Phase")
    dialog.name_edit.editingFinished.emit()
    assert [a.title for a in services.tabs.activities()] == ["Discovery Phase"]
    services.undo.undo()
    assert [a.title for a in services.tabs.activities()] == ["Discovery"]
    assert dialog.name_edit.text() == "Discovery"  # The echo of an undo reaches the field.
