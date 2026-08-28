"""The sync module over a multi-repo library: one Save, one scoped commit per repository.

The decisions pinned here: Save commits **each dirty repository once**, scoped to that
repository's project directories — never the user's own files beside them; the quit-time
dialog lists every dirty repository and commits exactly the checked ones; and the verbs are
always registered, gated by state rather than absence (a library's repositories change at
runtime, so there is no build-time capability to hide behind).
"""

import subprocess

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.seed import seed_project
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.sync import module as sync_module_mod
from dplanner.modules.sync.exit_dialog import DirtyRepoRow, ExitDialog


def sync_module(services):
    return next(m for m in services.modules if m.id == "sync")


def sync_service(services):
    service = sync_module(services).service
    assert service is not None
    return service


def commit_count(repo):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(result.stdout) if result.returncode == 0 else 0


def committed_paths(repo):
    """The paths the latest commit touched."""
    result = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format="],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def make_second_repo_project(services, tmp_path, title="Billing"):
    """A project in a repository of its own — the multi-repo half of the fixtures."""
    from dplanner.core.fsio import slugify

    repo = init_repo(tmp_path / "second-repo")
    directory = seed_project(repo / slugify(title, fallback="project"), title)
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
    return repo, project


def edit_and_flush(services, *projects):
    """A model edit in each project, on disk the way autosave puts it there."""
    for project in projects:
        services.document.set_field(project.id, "summary", f"edited {project.title}")
    services.autosave.flush_now()


def select_project(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )


# -- registration and gating -------------------------------------------------------------------


def test_the_save_and_branch_actions_are_always_registered(services):
    action_ids = {spec.id for spec in services.actions.all_specs()}
    assert {
        "sync.save",
        "sync.review_changes",
        "sync.new_branch",
        "sync.switch_branch",
        "sync.pull",
    } <= action_ids


def test_pull_without_any_remote_is_disabled_with_the_reason(services, make_project):
    make_project("Discovery")
    state = services.actions.spec("sync.pull").state(services.context.current())
    assert not state.enabled
    assert state.label is not None and "no remotes" in state.label


def test_branch_verbs_act_on_the_focused_project_only(services, make_project):
    project = make_project("Discovery")
    bare = services.context.current()
    for action_id in ("sync.new_branch", "sync.switch_branch"):
        state = services.actions.spec(action_id).state(bare)
        assert not state.enabled
        assert state.label is not None and "select a project first" in state.label

    select_project(services, project)
    chosen = services.context.current()
    for action_id in ("sync.new_branch", "sync.switch_branch"):
        assert services.actions.spec(action_id).state(chosen).enabled


# -- saving ------------------------------------------------------------------------------------


def test_saving_commits_what_autosave_wrote(services, make_project):
    project = make_project("Discovery")
    edit_and_flush(services, project)

    service = sync_service(services)
    service.refresh()
    (group,) = service.dirty_groups()
    service.save_sync("a test save")
    assert service.dirty_groups() == []
    assert group.history()[0].message == "a test save"


def test_saving_twice_reports_nothing_to_do(services, make_project):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    service = sync_service(services)
    notices: list[str] = []
    service.notice.connect(notices.append)
    service.save_sync("first")
    service.save_sync("second")
    assert notices[-1] == "Nothing new to save"


def test_one_save_commits_each_of_two_repositories_once(
    services, make_project, library_repo, tmp_path
):
    """Two projects in two repositories, edits in both: Save is one gesture, two commits."""
    first = make_project("Discovery")
    second_repo, second = make_second_repo_project(services, tmp_path)
    edit_and_flush(services, first, second)

    service = sync_service(services)
    service.refresh()
    assert len(service.dirty_groups()) == 2
    service.save_sync("both repos")

    assert commit_count(library_repo) == 1
    assert commit_count(second_repo) == 1
    assert service.dirty_groups() == []


def test_two_projects_in_one_repo_are_one_commit_scoped_to_their_directories(
    services, make_project, library_repo
):
    """The scoped-commit decision: a Save never sweeps up the user's own files."""
    first = make_project("Discovery")
    second = make_project("Billing")
    outside = library_repo / "notes.txt"
    outside.write_text("the user's own file, outside every project\n")
    edit_and_flush(services, first, second)

    service = sync_service(services)
    service.refresh()
    assert len(service.dirty_groups()) == 1  # One repository, however many projects.
    service.save_sync("one repo, both projects")

    assert commit_count(library_repo) == 1
    paths = committed_paths(library_repo)
    assert any(path.startswith("discovery/") for path in paths)
    assert any(path.startswith("billing/") for path in paths)
    assert all(path.startswith(("discovery/", "billing/")) for path in paths)

    # The stray file is untouched: still on disk, still untracked.
    assert outside.read_text().startswith("the user's own file")
    status = subprocess.run(
        ["git", "-C", str(library_repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "?? notes.txt" in status


# -- quitting ----------------------------------------------------------------------------------


def test_the_close_guard_offers_every_dirty_repo_and_commits_only_the_checked(
    services, make_project, library_repo, tmp_path, monkeypatch
):
    first = make_project("Discovery")
    second_repo, second = make_second_repo_project(services, tmp_path)
    edit_and_flush(services, first, second)

    module = sync_module(services)
    service = module.service
    service.refresh()
    assert len(service.dirty_groups()) == 2

    seen_rows: list[DirtyRepoRow] = []

    class CheckFirstOnly:
        """The user's answer, scripted: commit the first repository, leave the second."""

        DialogCode = ExitDialog.DialogCode

        def __init__(self, rows, _parent=None):
            seen_rows.extend(rows)
            self.discard = False

        def exec(self):
            return ExitDialog.DialogCode.Accepted

        def checked_rows(self):
            return [0]

        def message(self):
            return "quit-time save"

    monkeypatch.setattr(sync_module_mod, "ExitDialog", CheckFirstOnly)
    assert module._confirm_close(service) is True

    assert len(seen_rows) == 2
    remaining = service.dirty_groups()
    assert len(remaining) == 1  # The unchecked repository stays dirty for next time.
    assert commit_count(library_repo) + commit_count(second_repo) == 1


def test_a_clean_library_asks_nothing_on_close(services, make_project, monkeypatch):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    module = sync_module(services)
    module.service.save_sync("all recorded")

    def explode(*_args):
        raise AssertionError("no dialog should open when nothing is dirty")

    monkeypatch.setattr(sync_module_mod, "ExitDialog", explode)
    assert module._confirm_close(module.service) is True


# -- the exit dialog itself --------------------------------------------------------------------


@pytest.fixture
def rows():
    return [
        DirtyRepoRow(label="~/Code/widget · 3 files — Discovery"),
        DirtyRepoRow(label="~/Code/billing · 1 file — Billing"),
    ]


def test_the_dialog_renders_a_checked_row_per_repo(app, rows):
    dialog = ExitDialog(rows)
    assert [check.text() for check in dialog._checks] == [row.label for row in rows]
    assert dialog.checked_rows() == [0, 1]  # Everything checked is the default.
    assert dialog.message() == ""
    assert dialog.discard is False


def test_unchecking_a_row_takes_it_out_of_the_answer(app, rows):
    dialog = ExitDialog(rows)
    dialog._checks[0].setChecked(False)
    assert dialog.checked_rows() == [1]


def test_quit_without_committing_sets_the_discard_flag(app, rows):
    dialog = ExitDialog(rows)
    dialog._quit_without_committing()
    assert dialog.discard is True
    assert dialog.result() == ExitDialog.DialogCode.Accepted
