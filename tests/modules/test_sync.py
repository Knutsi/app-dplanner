"""The sync module over a multi-repo library: one Save, one scoped commit per repository.

The decisions pinned here: Save commits **each dirty repository once**, scoped to that
repository's project directories — never the user's own files beside them; the quit-time
dialog lists every dirty repository and commits exactly the checked ones; and the verbs are
always registered, gated by state rather than absence (a library's repositories change at
runtime, so there is no build-time capability to hide behind).
"""

import json
import subprocess
import time

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.seed import seed_project
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.tasks import ESTIMATE_CAP
from dplanner.modules.sync import module as sync_module_mod
from dplanner.modules.sync.exit_dialog import DirtyRepoRow, ExitDialog
from dplanner.modules.sync.save_progress import BAR_STEPS, SaveProgressDialog
from dplanner.modules.sync.service import COMMITTING, NOTHING, PUBLISHING, SAVED


def wait_for(qapp, done, timeout=10.0):
    """Pump until ``done()``; storage runs on a worker and reports back through Qt."""
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert done(), "the task never finished"


def settle(qapp, turns=4):
    """Turn the loop a few times: the exit save's outcome is decided one turn after busy."""
    for _ in range(turns):
        qapp.processEvents()


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
    services, make_project, library_repo, tmp_path, monkeypatch, qapp
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
    # Not "no" but "not yet": the save runs as a task under its progress dialog, and the
    # window closes when that ends. Nothing is torn down while it runs, which is what the
    # old synchronous save-at-quit existed to avoid.
    assert module._confirm_close(service) is False
    assert module._exit_progress is not None
    wait_for(qapp, lambda: not services.tasks.active())
    settle(qapp)

    assert len(seen_rows) == 2
    remaining = service.dirty_groups()
    assert len(remaining) == 1  # The unchecked repository stays dirty for next time.
    assert commit_count(library_repo) + commit_count(second_repo) == 1
    # And the guard now lets the window go, without asking a second time.
    assert module._exit_saved is True
    assert module._confirm_close(service) is True


class CommitEverything:
    """The user's answer, scripted: record every dirty repository and quit."""

    DialogCode = ExitDialog.DialogCode

    def __init__(self, rows, _parent=None):
        self.rows = list(rows)
        self.discard = False

    def exec(self):
        return ExitDialog.DialogCode.Accepted

    def checked_rows(self):
        return list(range(len(self.rows)))

    def message(self):
        return "quit-time save"


def test_a_quit_time_save_that_fails_stands_in_its_dialog_rather_than_being_lost(
    services, make_project, monkeypatch, qapp
):
    """The window is not closing yet, so the failure has somewhere to be read — and the
    person chooses between leaving without the version and staying to try again."""
    project = make_project("Discovery")
    edit_and_flush(services, project)
    module = sync_module(services)
    service = module.service
    service.refresh()

    def boom(*_args, **_kwargs):
        raise RuntimeError("the remote refused the push")

    monkeypatch.setattr(service, "save_sync", boom)
    monkeypatch.setattr(sync_module_mod, "ExitDialog", CommitEverything)
    assert module._confirm_close(service) is False
    wait_for(qapp, lambda: not services.tasks.active())
    settle(qapp)

    progress = module._exit_progress
    assert progress is not None  # Still up: a failure at quit must not vanish with the window.
    assert "refused the push" in progress.status.words()
    assert progress.status.tone() == "error"
    # Destructive last in Tab order, Stay the default — Enter records nothing by accident.
    assert [button.text() for button in progress.footer_buttons()] == ["Stay", "Close Anyway"]
    assert module._exit_saved is False


def test_staying_after_a_failed_quit_time_save_keeps_the_window_and_the_changes(
    services, make_project, monkeypatch, qapp
):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    module = sync_module(services)
    service = module.service
    service.refresh()
    monkeypatch.setattr(
        service, "save_sync", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no"))
    )
    monkeypatch.setattr(sync_module_mod, "ExitDialog", CommitEverything)
    module._confirm_close(service)
    wait_for(qapp, lambda: not services.tasks.active())
    settle(qapp)

    module._exit_progress.reject()  # "Stay"
    settle(qapp)
    assert module._exit_progress is None
    assert module._exit_saved is False
    assert len(service.dirty_groups()) == 1  # Nothing was recorded, and nothing was lost.


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


# -- a branch operation keeps the window ------------------------------------------------------


def test_new_branch_keeps_the_window_and_autosave_running(
    session, services, make_project, monkeypatch
):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    select_project(services, project)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("feature", True)))
    window = session.window
    services.undo.push(SetFieldCommand(project.id, "summary", "before the branch"))
    services.autosave.flush_now()

    services.actions.run("sync.new_branch", services.context.current())

    assert session.window is window
    assert services.undo.can_undo()  # Nothing on disk changed: the history is still true.
    services.document.set_field(project.id, "summary", "after the branch")
    services.autosave.flush_now()
    meta = json.loads((services.repo.project_dir(project.id) / "project.dproj").read_text())
    assert meta["summary"] == "after the branch"


def test_switch_branch_takes_the_checkout_in_place(session, services, make_project, monkeypatch):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    select_project(services, project)
    service = sync_service(services)
    group = services.repo.repo_for(project.id)
    service.save_sync("on main")
    main = service.branch_of(group)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("feature", True)))
    services.actions.run("sync.new_branch", services.context.current())
    services.document.set_field(project.id, "summary", "written on feature")
    services.autosave.flush_now()
    service.save_sync("on feature")
    services.undo.push(SetFieldCommand(project.id, "title", "Renamed on feature"))
    services.autosave.flush_now()

    window = session.window
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *_a, **_k: (main, True)))
    services.actions.run("sync.switch_branch", services.context.current())

    assert session.window is window
    assert services.document.projects[0].summary != "written on feature"
    assert services.document.projects[0].title == "Discovery"
    assert not services.undo.can_undo()  # The history described the other branch.
    assert not sync_module(services)._worktree_changed
    services.document.set_field(project.id, "summary", "back on main")
    services.autosave.flush_now()  # Autosave resumed with the tree in the model.
    meta = json.loads((services.repo.project_dir(project.id) / "project.dproj").read_text())
    assert meta["summary"] == "back on main"


def test_the_branch_label_asks_git_once_a_second(services, make_project, monkeypatch):
    """The label refreshes on every context change — twice per keystroke — and the answer
    is a subprocess; remembered for a second, an operation (which refreshes) still clears it."""
    from dplanner.core.storage.git import GitStorage

    make_project("Discovery")
    service = sync_service(services)
    (group,) = service.groups()
    asked = []
    original = GitStorage.current_branch

    def counted(self):
        asked.append(1)
        return original(self)

    monkeypatch.setattr(GitStorage, "current_branch", counted)

    first = service.branch_of(group)
    assert service.branch_of(group) == first and len(asked) == 1
    service.refresh()  # What every operation ends with: the next ask is fresh.
    assert service.branch_of(group) == first and len(asked) == 2


def test_a_step_added_to_a_project_asks_git_nothing(services, make_project, monkeypatch):
    """Membership is the library's children. A pasted step used to cost two subprocesses
    per repository — status and branch — on the GUI thread, for a fact it cannot change."""
    from dplanner.core.storage.git import GitStorage
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step

    project = make_project("Discovery")
    asked = []
    original = GitStorage._git

    def counted(self, *args, **kwargs):
        asked.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GitStorage, "_git", counted)

    services.undo.push(AddNodeCommand(project.id, Step(title="Read the spec")))
    assert asked == []
    make_project("Billing")  # A project joining the library is membership: git is asked.
    assert asked


# -- a branch switched underneath ---------------------------------------------------------------


def switch_outside(services, project, *args):
    """A git command in the project's repository, the way a terminal or an agent runs it."""
    subprocess.run(
        ["git", "-C", str(services.repo.project_dir(project.id)), *args],
        check=True,
        capture_output=True,
    )


def test_a_branch_switched_outside_the_window_is_taken_and_said(
    services, make_project, monkeypatch
):
    """`git checkout` in a terminal, or an agent working in the checkout: the plan on
    screen becomes another branch's. The poll takes the tree the way the window's own
    switch is taken — history dropped, autosave running again — and says which
    repository went from what to what, once."""
    project = make_project("Discovery")
    edit_and_flush(services, project)
    select_project(services, project)
    service = sync_service(services)
    (group,) = service.groups()
    service.save_sync("on main")
    main = service.branch_of(group)
    module = sync_module(services)
    services.undo.push(SetFieldCommand(project.id, "title", "Renamed on main"))
    services.autosave.flush_now()
    service.save_sync("renamed")

    switch_outside(services, project, "checkout", "-q", "-b", "feature")
    meta_path = services.repo.project_dir(project.id) / "project.dproj"
    meta = json.loads(meta_path.read_text())
    meta["summary"] = "written on feature"
    meta_path.write_text(json.dumps(meta, indent=2))
    switch_outside(services, project, "commit", "-q", "-am", "on feature")

    said = []

    def warned(_parent, title, text):
        said.append((title, text))

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warned))
    module._check_branches(service)

    assert len(said) == 1 and said[0][0] == "Branch changed"
    assert f"{group.label}: {main} → feature" in said[0][1]
    assert service.branch_of(group) == "feature"
    assert services.document.projects[0].summary == "written on feature"  # Taken in place.
    assert not services.undo.can_undo()  # The history described the other branch.
    module._check_branches(service)
    assert len(said) == 1  # Once per switch, not once per tick.

    services.document.set_field(project.id, "summary", "edited on feature")
    services.autosave.flush_now()  # Autosave resumed with the new tree in the model.
    assert json.loads(meta_path.read_text())["summary"] == "edited on feature"


def test_the_windows_own_switch_is_not_reported(session, services, make_project, monkeypatch):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    select_project(services, project)
    service = sync_service(services)
    service.save_sync("on main")
    module = sync_module(services)
    said = []

    def warned(*args):
        said.append(args)

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warned))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("feature", True)))
    services.actions.run("sync.new_branch", services.context.current())
    module._check_branches(service)
    assert said == []
    (group,) = service.groups()
    assert service.branch_of(group) == "feature"


def test_the_poll_stands_down_while_an_operation_runs(services, make_project, monkeypatch):
    project = make_project("Discovery")
    edit_and_flush(services, project)
    service = sync_service(services)
    module = sync_module(services)
    monkeypatch.setattr(service, "is_busy", lambda: True)
    asked = []
    from dplanner.core.storage.git import GitStorage

    def counted(_self):
        asked.append(1)
        return "x"

    monkeypatch.setattr(GitStorage, "current_branch", counted)
    module._check_branches(service)
    assert asked == []


# -- the progress dialog itself ----------------------------------------------------------------


def test_the_progress_dialog_carries_a_row_per_repository_and_counts_them(app):
    dialog = SaveProgressDialog(["~/Code/widget · 3 files — Discovery", "~/Code/billing · 1 file"])
    try:
        assert dialog.bar.value() == 0
        assert dialog._count.text() == "0 of 2 repositories recorded"
        dialog.step(0, PUBLISHING)
        assert dialog._rows[0].tone() == "busy" and "report site" in dialog._rows[0].words()
        dialog.step(0, COMMITTING)
        assert dialog._rows[0].tone() == "busy" and dialog.bar.value() == 0
        dialog.step(0, SAVED)
        assert dialog._rows[0].tone() == "ok" and dialog.bar.value() == BAR_STEPS // 2
        assert dialog._count.text() == "1 of 2 repositories recorded"
        # A repository that turns out clean still advances the count — the fraction counts
        # repositories dealt with, not commits made.
        dialog.step(1, NOTHING)
        assert dialog.bar.value() == BAR_STEPS and dialog._rows[1].tone() == "info"
    finally:
        dialog.deleteLater()


def test_a_remembered_duration_fills_the_bar_between_the_repositories_that_landed(app):
    """The count is a fact and leads; a previous run's duration only fills between steps."""
    dialog = SaveProgressDialog(["~/Code/widget", "~/Code/billing"], expected_seconds=10.0)
    try:
        # Two seconds into a save the last one took ten — dated from *now*, not from the
        # construction: whatever the build cost would otherwise be added to the elapsed time,
        # and a cold import made a tenth read as 0.204.
        dialog._started = time.monotonic() - 2.0
        dialog._redraw()
        assert dialog.bar.value() == round(0.2 * BAR_STEPS)
        dialog.step(0, SAVED)  # A repository landing outruns the estimate: the fact leads.
        assert dialog.bar.value() == BAR_STEPS // 2
        dialog._started = time.monotonic() - 100.0  # Long past what the last run took.
        dialog._redraw()
        assert dialog.bar.value() == round(ESTIMATE_CAP * BAR_STEPS)  # Never falsely full.
    finally:
        dialog.deleteLater()


def test_with_nothing_remembered_the_bar_is_the_repositories_alone(app):
    dialog = SaveProgressDialog(["~/Code/widget", "~/Code/billing"])
    try:
        assert not dialog._tick.isActive()  # Nothing to tick towards.
        dialog._started -= 100.0
        dialog._redraw()
        assert dialog.bar.value() == 0
    finally:
        dialog.deleteLater()


def test_the_progress_dialog_refuses_escape_while_the_save_runs(app):
    """A save nobody can see is what this replaced; dismissing it would restore exactly that."""
    dialog = SaveProgressDialog(["~/Code/widget"])
    try:
        ended: list[int] = []
        dialog.finished.connect(ended.append)
        dialog.reject()
        assert ended == []
        dialog.stopped("git said no")
        dialog.reject()
        assert ended == [int(ExitDialog.DialogCode.Rejected)]
    finally:
        dialog.deleteLater()


def test_a_row_still_working_when_the_save_failed_says_it_was_not_recorded(app):
    dialog = SaveProgressDialog(["~/Code/widget · 3 files — Discovery"])
    try:
        dialog.step(0, COMMITTING)
        dialog.stopped("git said no")
        assert dialog._rows[0].tone() == "error"
        assert dialog._rows[0].words() == "~/Code/widget · 3 files — Discovery — not recorded"
    finally:
        dialog.deleteLater()


def test_the_diff_dialog_is_on_the_frame_with_save_now_as_the_primary(app):
    """The picker's block — caption and combo — shows only when the library spans more
    than one repository, and Save Now is asked for, never run, by the dialog."""
    from dplanner.framework.dialog import DialogFrame
    from dplanner.modules.sync.view import DiffDialog

    dialog = DiffDialog(None)
    asked = []
    dialog.save_requested.connect(lambda: asked.append(True))
    try:
        assert isinstance(dialog, DialogFrame)
        assert [b.text() for b in dialog.footer_buttons()] == ["Save Now", "Close"]
        assert dialog.save_button.isDefault()
        dialog.set_sources([("plans", lambda: "+one")])
        assert dialog._picker_block.isHidden()
        dialog.set_sources([("plans", lambda: "+one"), ("widget", lambda: "-two")])
        assert not dialog._picker_block.isHidden() and dialog._picker.count() == 2
        dialog.save_button.click()
        assert asked == [True]
    finally:
        dialog.deleteLater()
