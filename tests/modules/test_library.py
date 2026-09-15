"""The library module: New/Open Project Library as spawned instances, and the title.

Project membership — New Project…, Open Project… — is the projects module's now
(``test_open_projects.py``); this module says which *library* a window holds.
"""

import pytest
from PySide6.QtWidgets import QFileDialog

from dplanner.cli.main import WINDOW_WORD
from dplanner.identity import APP_NAME
from dplanner.modules.library import module as library_module


def run(services, action_id):
    services.actions.run(action_id, services.context.current())


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
    assert command[-3:] == [WINDOW_WORD, "--library", str(target)]
    assert kwargs["start_new_session"] is True


def test_open_library_spawns_a_detached_instance(services, tmp_path, monkeypatch, spawned):
    from dplanner.domain.seed import create_library

    target = tmp_path / "client-work.json"
    create_library(target)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))

    run(services, "library.open_library")
    command, kwargs = spawned[0]
    assert command[-3:] == [WINDOW_WORD, "--library", str(target)]
    assert kwargs["start_new_session"] is True


# -- the window's title ------------------------------------------------------------------------


def test_the_window_title_is_the_library_file_stem(services, library_file):
    assert services.window.windowTitle() == f"{library_file.stem} — {APP_NAME}"


def test_the_default_library_titles_the_window_plain(app, library_file, monkeypatch):
    """ "DPlanner" *is* the user's planner; only an alternative library needs pointing out."""
    from dplanner.app import new_session

    monkeypatch.setattr(library_module, "default_library_path", lambda: library_file)
    session = new_session()
    assert session.open_initial(library_file)
    try:
        assert session.window is not None
        assert session.window.windowTitle() == APP_NAME
    finally:
        session.close()
