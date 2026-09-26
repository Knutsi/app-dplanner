"""The archive: a project out of the library and kept listed, and the way back.

Per user, in the library file — archiving is one person's tidying, never a fact about the
plan. The verbs are tested as functions of a constructed ``Context``; the Archive tab and
the index's Archive folder as the views a person reaches them through.
"""

import shutil

import pytest

from dplanner.domain.library_file import read_library_file
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import module as projects_module
from dplanner.modules.projects import verbs
from dplanner.modules.projects.archive_tab import ARCHIVE_KIND, NOTHING_ARCHIVED, ArchiveActivity
from dplanner.modules.projects.verbs import ARCHIVED_KIND


@pytest.fixture
def project(make_project):
    return make_project("Discovery")


def select(services, kind, node_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri(kind, node_id)),))
    return services.context.current()


def state(services, action_id, context):
    return services.actions.spec(action_id).state(context)


def archive(services, project):
    directory = services.repo.project_dir(project.id)
    services.actions.run("projects.archive", select(services, "project", project.id))
    return directory


def archive_tab(services):
    services.actions.run("projects.show_archive", services.context.current())
    found = [a for a in services.tabs.activities() if isinstance(a, ArchiveActivity)]
    assert len(found) == 1
    return found[0]


def archive_folder(services):
    tree = services.window.dock.widget_for(INDEX_PANEL_ID).tree
    roots = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    return tree, next(root for root in roots if root.text(0) == "Archive")


# -- archiving ---------------------------------------------------------------------------------


def test_archiving_takes_the_project_out_and_keeps_it_listed(services, project):
    services.tabs.open("project", project.id)

    directory = archive(services, project)

    assert services.document.projects == []
    assert services.tabs.activities() == []  # Its tabs went with it.
    assert services.repo.archived() == [directory]
    services.autosave.flush_now()
    file = read_library_file(services.repo.library_path)
    assert (file.projects, file.archived) == ([], [directory])
    _tree, folder = archive_folder(services)
    assert [folder.child(i).text(0) for i in range(folder.childCount())] == ["Discovery"]


def test_a_project_whose_edits_cannot_reach_disk_is_not_archived(services, project, monkeypatch):
    """An archived project is never saved again, so it leaves only once its edits have."""
    told = []
    monkeypatch.setattr(services.autosave, "flush_now", lambda: None)
    monkeypatch.setattr(projects_module, "notice", lambda _p, title, text: told.append(text))
    services.document.set_field(project.id, "summary", "not yet on disk")

    services.actions.run("projects.archive", select(services, "project", project.id))

    assert [p.id for p in services.document.projects] == [project.id]
    assert services.repo.archived() == []
    assert "could not be written to disk" in told[0]


# -- the verbs' states -------------------------------------------------------------------------


def test_the_membership_verbs_say_what_they_need(services, project):
    bare = services.context.current()
    assert "pick an archived project" in state(services, "projects.restore", bare).label
    on_project = select(services, "project", project.id)
    assert state(services, "projects.archive", on_project).enabled
    assert not state(services, "projects.restore", on_project).enabled

    directory = archive(services, project)
    on_archived = select(services, ARCHIVED_KIND, str(directory))
    assert not state(services, "projects.archive", on_archived).enabled
    assert state(services, "projects.restore", on_archived).enabled
    assert state(services, "projects.remove", on_archived).enabled
    assert state(services, "projects.show_archive", bare).enabled

    shutil.rmtree(directory)
    gone = state(services, "projects.restore", on_archived)
    assert not gone.enabled and "its folder is gone" in gone.label
    assert state(services, "projects.remove", on_archived).enabled  # Still forgettable.


# -- restoring and forgetting ------------------------------------------------------------------


def test_restore_brings_the_project_back(services, project):
    directory = archive(services, project)

    services.actions.run("projects.restore", select(services, ARCHIVED_KIND, str(directory)))

    assert [p.id for p in services.document.projects] == [project.id]
    assert services.repo.archived() == []
    services.autosave.flush_now()
    file = read_library_file(services.repo.library_path)
    assert (file.projects, file.archived) == ([directory], [])


def test_remove_on_an_archived_project_forgets_it_and_keeps_its_files(
    services, project, monkeypatch
):
    asked = []

    def fake_confirm(_parent, _title, question, **_kwargs):
        asked.append(question)
        return True

    monkeypatch.setattr(verbs, "confirm", fake_confirm)
    directory = archive(services, project)

    services.actions.run("projects.remove", select(services, ARCHIVED_KIND, str(directory)))

    assert services.repo.archived() == []
    assert "archive" in asked[0] and "files stay on disk" in asked[0]
    assert (directory / "project.dproj").is_file()
    services.autosave.flush_now()
    assert read_library_file(services.repo.library_path).archived == []


# -- the Archive tab ---------------------------------------------------------------------------


def test_the_tab_says_when_nothing_is_archived(services):
    tab = archive_tab(services)
    assert tab.title == "Archive" and tab.empty.text() == NOTHING_ARCHIVED


def test_the_tab_lists_the_archive_and_follows_it(services, project, make_project):
    tab = archive_tab(services)
    directory = archive(services, project)
    assert tab.table.rowCount() == 1
    assert [tab.table.item(0, column).text() for column in range(3)] == [
        "Discovery",
        "0",
        str(directory),
    ]
    assert tab.empty.text() == ""

    shutil.rmtree(directory)
    archive(services, make_project("Billing"))  # Any change to the list redraws it.
    assert tab.table.item(0, 0).text() == "discovery — folder missing"


def test_the_tab_publishes_its_pick_only_while_current(services, project):
    directory = archive(services, project)
    tab = archive_tab(services)
    tab.on_deactivated()
    services.context.set_scope(SCOPE_SELECTION, ())
    tab.pick(directory)
    assert services.context.current().selected_entity(ARCHIVED_KIND) is None

    tab.on_activated()
    assert services.context.current().selected_entity(ARCHIVED_KIND) == str(directory)
    menu = tab.row_menu()
    try:
        entries = [a.text().replace("&", "") for a in menu.actions() if a.text()]
        assert entries == [
            "Archive Project",
            "Restore Project",
            "Remove from Library…",
            "Show Archive",
        ]
    finally:
        menu.deleteLater()


def test_activating_an_archived_row_in_the_index_opens_the_tab_on_it(services, project):
    directory = archive(services, project)
    tree, folder = archive_folder(services)

    tree.itemActivated.emit(folder.child(0), 0)

    tab = next(a for a in services.tabs.activities() if isinstance(a, ArchiveActivity))
    assert tab.uri.endswith(ARCHIVE_KIND) and tab.picked() == directory
