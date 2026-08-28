"""The library module: File's project membership verbs, spawned instances, and the title.

Dialogs are monkeypatched at the names the module reads; what is under test is everything
around them — what gets seeded on disk, attached to the store, added to the model, refused
with a reason, or handed to a brand-new process.
"""

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from dplanner.domain.store import PROJECT_META
from dplanner.identity import APP_NAME
from dplanner.modules.library import module as library_module


def run(services, action_id):
    services.actions.run(action_id, services.context.current())


@pytest.fixture
def boxes(monkeypatch):
    """Every QMessageBox the flow shows, recorded instead of blocking the suite."""
    shown = []

    def fake_exec(self):
        shown.append((self.windowTitle(), self.text(), self.informativeText()))
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return shown


# -- New Project… ------------------------------------------------------------------------------


def test_new_project_inside_a_repo_is_seeded_and_added(services, library_repo, monkeypatch):
    target = library_repo / "alpha-search"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    run(services, "library.new_project")
    assert (target / PROJECT_META).is_file()
    assert [p.title for p in services.document.projects] == ["Alpha Search"]
    project = services.document.projects[0]
    assert services.repo.project_dir(project.id) == target.resolve()


def test_new_project_outside_a_repo_offers_git_init(services, tmp_path, monkeypatch, boxes):
    """The dialog's accept path really initialises: the project lands in a fresh repo."""
    target = tmp_path / "solo"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    def accept_init(self):
        # The "Initialize Repository" button is the one added with the accept role.
        return next(
            button
            for button in self.buttons()
            if self.buttonRole(button) == QMessageBox.ButtonRole.AcceptRole
        )

    monkeypatch.setattr(QMessageBox, "clickedButton", accept_init)

    run(services, "library.new_project")
    assert boxes and "not inside a git repository" in boxes[0][1]
    assert (target / ".git").is_dir()
    assert (target / PROJECT_META).is_file()
    assert [p.title for p in services.document.projects] == ["Solo"]


# -- Open Project… -----------------------------------------------------------------------------


def test_open_project_refuses_a_dir_without_project_meta(
    services, library_repo, monkeypatch, boxes
):
    target = library_repo / "just-code"
    target.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(target))

    run(services, "library.open_project")
    assert services.document.projects == []
    assert boxes and f"No {APP_NAME} project here." in boxes[0][1]


def test_open_project_refuses_a_dir_outside_any_repo(services, tmp_path, monkeypatch, boxes):
    from dplanner.domain.seed import seed_project

    target = seed_project(tmp_path / "stray", "Stray")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(target))

    run(services, "library.open_project")
    assert services.document.projects == []
    assert boxes and "not inside a git repository" in boxes[0][1]


def test_opening_an_already_listed_project_is_a_no_op_with_a_notice(
    services, make_project, monkeypatch
):
    project = make_project("Discovery")
    directory = services.repo.project_dir(project.id)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(directory))

    run(services, "library.open_project")
    assert [p.id for p in services.document.projects] == [project.id]
    assert "already in this library" in services.window.statusBar().currentMessage()


# -- New/Open Project Library: a peer process, never a switch ----------------------------------


@pytest.fixture
def spawned(monkeypatch):
    """Popen recorded: a new library is another process, and the suite must not start one."""
    launched = []

    def fake_popen(command, **kwargs):
        launched.append((list(command), kwargs))

    monkeypatch.setattr("dplanner.modules.library.module.subprocess.Popen", fake_popen)
    return launched


def test_new_library_creates_the_file_and_spawns_a_detached_instance(
    services, tmp_path, monkeypatch, spawned
):
    target = tmp_path / "client-work.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    run(services, "library.new_library")
    assert target.is_file()  # Created before the new instance opens it.
    command, kwargs = spawned[0]
    assert command[-2:] == ["--library", str(target)]
    assert kwargs["start_new_session"] is True


def test_open_library_spawns_a_detached_instance(services, tmp_path, monkeypatch, spawned):
    from dplanner.domain.seed import create_library

    target = tmp_path / "client-work.json"
    create_library(target)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))

    run(services, "library.open_library")
    command, kwargs = spawned[0]
    assert command[-2:] == ["--library", str(target)]
    assert kwargs["start_new_session"] is True


# -- the window's title ------------------------------------------------------------------------


def test_the_window_title_is_the_library_file_stem(services, library_file):
    assert services.window.windowTitle() == f"{library_file.stem} — {APP_NAME}"


def test_the_default_library_titles_the_window_plain(
    app, library_file, close_quietly, monkeypatch
):
    """"DPlanner" *is* the user's planner; only an alternative library needs pointing out."""
    from dplanner.app import new_session

    monkeypatch.setattr(library_module, "default_library_path", lambda: library_file)
    session = new_session()
    assert session.open_initial(library_file)
    try:
        assert session.window is not None
        assert session.window.windowTitle() == APP_NAME
    finally:
        close_quietly(session)
