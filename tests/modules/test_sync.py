"""The sync module: what it registers, and — more importantly — what it refuses to.

This is the capability design's regression test. Against a plain folder the module must add
nothing at all: an application that shows Save and then quietly does nothing is worse than
one that shows no Save.
"""

import subprocess

import pytest

from dplanner.app import new_session
from dplanner.core.storage.locations import StorageLocation
from dplanner.modules.sync.service import SyncService


@pytest.fixture
def plain_session(app, tmp_path, close_quietly):
    session = new_session()
    assert session.open_initial(StorageLocation(scheme="", target=str(tmp_path / "plain")))
    yield session
    close_quietly(session)


@pytest.fixture
def git_session(app, tmp_path, close_quietly):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)
    session = new_session()
    assert session.open_initial(StorageLocation(scheme="", target=str(repo / "workspace")))
    yield session
    close_quietly(session)


def test_a_plain_folder_gets_no_save_action(plain_session):
    action_ids = {spec.id for spec in plain_session.services.actions.all_specs()}
    assert not any(action_id.startswith("sync.") for action_id in action_ids)


def test_a_git_workspace_gets_the_save_actions(git_session):
    action_ids = {spec.id for spec in git_session.services.actions.all_specs()}
    assert {"sync.save", "sync.review_changes", "sync.switch_branch"} <= action_ids


def test_a_local_repo_offers_no_remote_update(git_session):
    """No origin, so no Update — the second capability, checked separately."""
    action_ids = {spec.id for spec in git_session.services.actions.all_specs()}
    assert "sync.pull" not in action_ids


def test_saving_commits_what_autosave_wrote(git_session, tmp_path):
    services = git_session.services
    library = services.document
    library.set_field(library.id, "repository", "edited in the test")
    services.autosave.flush_now()

    storage = services.storage
    storage.refresh_dirty()
    assert storage.is_dirty()
    service = SyncService(storage, services.tasks)
    service.save_sync("a test save")
    storage.refresh_dirty()
    assert not storage.is_dirty()
    assert storage.history()[0].message == "a test save"


def test_saving_twice_reports_nothing_to_do(git_session):
    services = git_session.services
    service = SyncService(services.storage, services.tasks)
    notices: list[str] = []
    service.notice.connect(notices.append)
    service.save_sync("first")
    service.save_sync("second")
    assert notices[-1] == "Nothing new to save"
