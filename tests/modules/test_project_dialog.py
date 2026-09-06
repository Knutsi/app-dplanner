"""The Project dialog and the Repositories card: where a project's plan and code live.

The dialog is built over a ``RepositoryServices`` of lambdas — git and gh never run — and
its task bodies are run inline, so what a worker thread would deliver arrives on the line
after the request. What is under test is everything around the fakes: which field commits
which fact through which path, what the two columns show, and what the plan column offers
while the plan has no repository of its own.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.domain.relocate import Moved
from dplanner.domain.repositories import ACCEPTED, repository_facts
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import repositories_folder as folders
from dplanner.modules.projects.repos import (
    LogEntry,
    PullRequest,
    RepoLog,
    RepositoryServices,
    candidate_repositories_folders,
)
from dplanner.modules.projects.settings_dialog import CREATE, ProjectDialog

CODE_URL = "https://github.com/acme/widget"


def commit_now():
    """A commit stamped when asked for, so the row reads "just now" however long the
    suite has been running since this module was collected."""
    return LogEntry("abc123", "Add the login form", "anna", datetime.now(UTC).isoformat())


PR = PullRequest(7, "Build the modal", "feat/login", "https://github.com/acme/widget/pull/7")


def select(services, project_id):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project_id)),)
    )
    return services.context.current()


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    return project


@pytest.fixture
def fakes(services):
    """A ``RepositoryServices`` over the real store's facts and fake git and gh."""
    calls: dict[str, list[object]] = {"clone": [], "publish": [], "create": [], "history": []}
    store, library = services.repo, services.document

    def facts_of(project_id):
        return repository_facts(
            library.project(project_id),
            store.project_dir(project_id),
            store.checkout_of(project_id),
        )

    def history_for(root, scope, limit):
        calls["history"].append((root, scope))
        return RepoLog(branch="main", entries=(commit_now(),))

    def clone(url, dest):
        calls["clone"].append((url, dest))
        dest.mkdir(parents=True)

    def publish(root, name):
        calls["publish"].append((root, name))
        return f"https://github.com/acme/{name}"

    def create(name, dest):
        calls["create"].append((name, dest))
        dest.mkdir(parents=True)
        return f"https://github.com/acme/{name}"

    state: dict[str, object] = {"gh": None, "prs": [PR]}
    services_ = RepositoryServices(
        facts_of=facts_of,
        project_dir=store.project_dir,
        set_checkout=store.set_checkout,
        checkout_changed=store.checkout_changed,
        plan_roots=lambda: [],
        pr_steps=lambda project_id: {7: "S1 Read the spec"},
        history_for=history_for,
        gh_refusal=lambda: str(state["gh"]) if state["gh"] else None,
        list_repositories=lambda: ["acme/widget", "acme/plans"],
        clone=clone,
        publish=publish,
        create_repository=create,
        open_prs=lambda remote: list(state["prs"]),  # type: ignore[call-overload]
        move_project=lambda *_args: Moved(Path(), Path(), False, False, ()),
    )
    return services_, calls, state


@pytest.fixture
def dialog(services, fakes, project, monkeypatch):
    repos, _calls, _state = fakes
    moved: list[str] = []
    built = ProjectDialog(
        services.document,
        services.undo,
        repos,
        services.tasks,
        services.theme,
        move=moved.append,
        parent=services.window,
    )
    built.moved = moved  # type: ignore[attr-defined]
    inline(built, monkeypatch)
    built.show_project(project.id)
    yield built
    built.deleteLater()


def inline(dialog, monkeypatch):
    """Run every task body on the spot: the answer lands on the line after the request."""

    def run_now(_label, body, **_kwargs):
        body()
        return True

    for runner in (dialog._reader, dialog._worker):
        monkeypatch.setattr(runner, "run", run_now)


def separate(services, project, tmp_path):
    """The shape the application wants: the code recorded and checked out elsewhere."""
    code = init_repo(tmp_path / "widget")
    services.undo.push(SetFieldCommand(project.id, "repository", CODE_URL))
    services.repo.set_checkout(project.id, code)
    return code


# -- the settings -------------------------------------------------------------------------------


def test_the_code_repository_is_committed_through_the_undo_stack(services, dialog, project):
    dialog.repository_combo.setEditText(CODE_URL)
    dialog.repository_combo.lineEdit().editingFinished.emit()
    assert services.document.project(project.id).repository == CODE_URL
    assert services.undo.undo_text() == "Set Code Repository"
    services.undo.undo()
    assert services.document.project(project.id).repository == ""
    assert dialog.repository_combo.currentText() == ""  # The undo's echo reaches the field.


def test_a_typed_checkout_is_recorded_in_the_library_file_not_the_undo_stack(
    services, dialog, project, tmp_path
):
    code = init_repo(tmp_path / "widget")
    services.autosave.flush_now()
    before = services.undo.undo_text()
    dialog.checkout_edit.setText(str(code))
    dialog.checkout_edit.editingFinished.emit()
    assert services.repo.checkout_of(project.id) == code
    assert services.undo.undo_text() == before
    assert not services.autosave.has_pending()  # Written directly, nothing left to flush.


def test_browse_records_the_checkout_and_fills_an_empty_repository_from_its_origin(
    services, dialog, project, tmp_path, monkeypatch
):
    import subprocess

    code = init_repo(tmp_path / "widget")
    subprocess.run(["git", "-C", str(code), "remote", "add", "origin", CODE_URL], check=True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(code / "src"))
    (code / "src").mkdir()
    dialog.browse_button.click()
    assert services.repo.checkout_of(project.id) == code  # The repository root, not src/.
    assert services.document.project(project.id).repository == CODE_URL


def test_keep_it_here_accepts_the_colocation_and_quiets_the_warning(services, dialog, project):
    assert dialog.warning_row.isVisibleTo(dialog)
    assert dialog.plan_column.setup_button.objectName() == "PrimaryButton"
    dialog.keep_button.click()
    assert services.document.project(project.id).colocation == ACCEPTED
    assert not dialog.warning_row.isVisibleTo(dialog)
    assert dialog.plan_column.setup_button.objectName() == "PlanSetupButton"  # Quiet now.
    assert dialog.plan_column.pages.currentWidget() is dialog.plan_column.setup


def test_the_setup_button_and_the_move_glyph_both_open_the_move_wizard(dialog, project):
    dialog.plan_column.setup_button.click()
    dialog.move_button.click()
    assert dialog.moved == [project.id, project.id]


# -- the logs -----------------------------------------------------------------------------------


def test_a_plan_beside_its_code_shows_one_log_and_offers_setup(dialog, fakes, library_repo):
    _repos, calls, _state = fakes
    assert calls["history"] == [(library_repo, "")]  # The plan's repository is the code's.
    assert dialog.code_column.rows() == [("Add the login form", "anna · just now")]
    assert dialog.code_column.branch.text() == "main"
    assert dialog.plan_column.pages.currentWidget() is dialog.plan_column.setup


def test_a_separated_plan_fills_both_columns_and_prs_lead_the_code_column(
    services, dialog, fakes, project, tmp_path, library_repo
):
    _repos, calls, _state = fakes
    code = separate(services, project, tmp_path)
    assert (code, "") in calls["history"] and (library_repo, "discovery") in calls["history"]
    assert dialog.code_column.rows() == [
        ("#7 Build the modal", "S1 Read the spec · feat/login"),
        ("Add the login form", "anna · just now"),
    ]
    assert dialog.plan_column.rows() == [("Add the login form", "anna · just now")]
    assert dialog.plan_column.pages.currentWidget() is dialog.plan_column.well
    assert not dialog.warning_row.isVisibleTo(dialog)


def test_an_answer_for_a_project_the_dialog_left_is_dropped(
    services, fakes, project, make_project, monkeypatch
):
    repos, _calls, _state = fakes
    other = make_project("Satellite")
    dialog = ProjectDialog(
        services.document,
        services.undo,
        repos,
        services.tasks,
        services.theme,
        move=lambda _pid: None,
        parent=services.window,
    )
    pending = []

    def hold(_label, body, **_kwargs):
        pending.append(body)
        return True

    monkeypatch.setattr(dialog._reader, "run", hold)
    dialog.show_project(project.id)
    dialog.show_project(other.id)
    pending[0]()  # Discovery's answer arrives after the dialog moved to Satellite.
    assert dialog.code_column.rows() == []
    pending[1]()
    assert dialog.code_column.rows() == [("Add the login form", "anna · just now")]
    dialog.deleteLater()


def test_a_missing_checkout_is_said_in_the_code_column(services, fakes, dialog, project):
    """Pull requests come from GitHub and show without a checkout; with none open, the
    column says what is missing instead of standing empty."""
    _repos, _calls, state = fakes
    services.undo.push(SetFieldCommand(project.id, "repository", CODE_URL))
    assert dialog.code_column.rows() == [("#7 Build the modal", "S1 Read the spec · feat/login")]
    state["prs"] = []
    dialog.show_project(project.id)
    assert dialog.code_column.pages.currentWidget() is dialog.code_column.empty
    assert "Not checked out" in dialog.code_column.empty.text()


# -- gh ---------------------------------------------------------------------------------------


def test_without_gh_clone_and_new_are_greyed_and_the_note_says_why(
    services, fakes, project, dialog
):
    _repos, _calls, state = fakes
    state["gh"] = "gh not found on PATH — GitHub features need the GitHub CLI"
    dialog.show_project(project.id)
    assert dialog.gh_note.isVisibleTo(dialog) and "gh not found" in dialog.gh_note.text()
    assert not dialog.clone_button.isEnabled() and not dialog.new_code_button.isEnabled()
    state["gh"] = None
    dialog.show_project(project.id)
    assert not dialog.gh_note.isVisibleTo(dialog)
    assert dialog.new_code_button.isEnabled()  # No repository yet: create one.
    assert not dialog.clone_button.isEnabled()  # Nothing to clone yet.


def test_clone_lands_in_the_repositories_folder_and_records_the_checkout(
    services, fakes, dialog, project, tmp_path
):
    _repos, calls, _state = fakes
    folders.set_repositories_folder(tmp_path / "Code")
    services.undo.push(SetFieldCommand(project.id, "repository", CODE_URL))
    assert dialog.clone_button.isEnabled()
    dialog.clone_button.click()
    assert calls["clone"] == [(CODE_URL, tmp_path / "Code" / "widget")]
    assert services.repo.checkout_of(project.id) == tmp_path / "Code" / "widget"
    assert "Cloned into" in dialog.note.text()


def test_a_new_code_repository_is_created_cloned_and_recorded(
    services, fakes, dialog, project, tmp_path, monkeypatch
):
    _repos, calls, _state = fakes
    folders.set_repositories_folder(tmp_path / "Code")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("widget", True))
    dialog.new_code_button.click()
    assert calls["create"] == [("widget", tmp_path / "Code" / "widget")]
    assert services.document.project(project.id).repository == "https://github.com/acme/widget"
    assert services.repo.checkout_of(project.id) == tmp_path / "Code" / "widget"


def test_publish_is_offered_only_for_a_plan_repository_without_an_origin(
    services, fakes, dialog, project, library_repo, monkeypatch
):
    import subprocess

    _repos, calls, _state = fakes
    assert dialog.publish_button.isVisibleTo(dialog)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("plans", True))
    dialog.publish_button.click()
    assert calls["publish"] == [(library_repo, "plans")]
    assert "Published as acme/plans" in dialog.note.text()

    subprocess.run(
        [
            "git",
            "-C",
            str(library_repo),
            "remote",
            "add",
            "origin",
            "git@github.com:acme/plans.git",
        ],
        check=True,
    )
    dialog.show_project(project.id)
    assert not dialog.publish_button.isVisibleTo(dialog)
    assert dialog.plan_label.text() == "acme/plans"


# -- the card -------------------------------------------------------------------------------


def _card(services, project):
    select(services, project.id)
    panel = services.window.dock.widget_for("project_editor.project")
    return next(c for c in panel._cards if c.title.text() == "Repositories").body


def test_the_card_states_both_repositories_and_follows_the_facts(
    services, project, tmp_path, library_repo
):
    card = _card(services, project)
    assert card.plan_text.text() == "repo"  # The plan repository's folder: no origin yet.
    assert card.code_text.text() == "no code repository recorded"
    assert card.note.isVisibleTo(card) and "inside the code" in card.note.text()
    assert card.move_button.text() == "Set up a plan repository…"

    separate(services, project, tmp_path)
    assert card.code_text.text() == "acme/widget"
    assert card.checkout_text.text().endswith("widget")
    assert not card.note.isVisibleTo(card)
    assert card.move_button.text() == "Move Plan…"


def test_the_cards_buttons_run_the_registry_verbs(services, project, monkeypatch):
    card = _card(services, project)
    ran = []
    monkeypatch.setattr(services.actions, "run", lambda action_id, _context: ran.append(action_id))
    card.settings_button.click()
    card.move_button.click()
    assert ran == ["projects.settings", "projects.move"]


# -- the repositories folder ----------------------------------------------------------------


def test_candidate_folders_prefer_what_exists_and_fall_back_to_code(tmp_path):
    assert candidate_repositories_folders(tmp_path) == [tmp_path / "Code"]
    (tmp_path / "src").mkdir()
    (tmp_path / "repos").mkdir()
    assert candidate_repositories_folders(tmp_path) == [tmp_path / "src", tmp_path / "repos"]


def test_the_repositories_folder_is_asked_once_then_remembered(app, tmp_path, monkeypatch):
    asked = []

    def accept(self):
        asked.append([self.list.item(i).text() for i in range(self.list.count())])
        return 1

    monkeypatch.setattr(folders.RepositoriesFolderDialog, "exec", accept)
    (tmp_path / "src").mkdir()
    first = folders.ensure_repositories_folder(None, home=tmp_path)
    assert first == tmp_path / "src" and len(asked) == 1
    again = folders.ensure_repositories_folder(None, home=tmp_path)
    assert again == first and len(asked) == 1  # Remembered: not asked twice.
    assert folders.repositories_folder() == first


def test_cancelling_the_folder_question_remembers_nothing(app, tmp_path, monkeypatch):
    monkeypatch.setattr(folders.RepositoriesFolderDialog, "exec", lambda self: 0)
    assert folders.ensure_repositories_folder(None, home=tmp_path) is None
    assert folders.repositories_folder() is None


# -- opening ------------------------------------------------------------------------------------


def test_opening_says_which_plan_lives_inside_its_code(app, library_file, library_repo):
    from dplanner.app import new_session
    from dplanner.domain.seed import seed_project
    from dplanner.domain.store import LibraryStore

    store = LibraryStore(library_file)
    library = store.load()
    project = store.attach(seed_project(library_repo / "discovery", "Discovery"))
    library.add_child(library.id, project)
    store.flush({(library.id, "structure")})
    store.close()

    session = new_session()
    assert session.open_initial(library_file)
    try:
        assert session.services is not None
        message = session.services.window.statusBar().currentMessage()
        assert "“Discovery” lives inside its code repository" in message
    finally:
        session.close()


# -- create mode --------------------------------------------------------------------------------


def test_create_mode_answers_a_spec_once_a_name_and_a_home_are_given(
    services, fakes, tmp_path, monkeypatch
):
    """The same dialog, nothing to edit: a name, a plan repository, a folder — the folder
    follows the name until it is typed in — and the code fields ride along."""
    import subprocess

    repos, _calls, _state = fakes
    dialog = ProjectDialog(
        services.document,
        services.undo,
        repos,
        services.tasks,
        services.theme,
        move=lambda _pid: None,
        mode=CREATE,
        parent=services.window,
    )
    assert dialog.plan_picker is not None and dialog.folder_edit is not None
    assert not dialog.create_button.isEnabled()
    assert not dialog.plan_label.isVisibleTo(dialog) and not dialog.publish_button.isVisibleTo(
        dialog
    )

    dialog.name_edit.setText("Alpha Search")
    assert dialog.folder_edit.text() == "alpha-search"
    plans = init_repo(tmp_path / "plans")
    dialog.plan_picker.set_current(plans)
    assert dialog.create_button.isEnabled()

    code = init_repo(tmp_path / "widget")
    subprocess.run(["git", "-C", str(code), "remote", "add", "origin", CODE_URL], check=True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(code))
    dialog.browse_button.click()
    assert dialog.repository_combo.currentText() == CODE_URL  # From the checkout's origin.

    spec = dialog.spec()
    assert spec is not None
    assert spec.target == plans / "alpha-search" and spec.plan.root == plans
    assert spec.title == "Alpha Search" and spec.repository == CODE_URL and spec.checkout == code
    assert services.document.projects == []  # The dialog wrote nothing anywhere.

    (plans / "alpha").mkdir()
    dialog.folder_edit.setText("alpha")
    dialog.folder_edit.textEdited.emit("alpha")
    assert not dialog.create_button.isEnabled() and "already exists" in dialog.target_label.text()
    dialog.name_edit.setText("Alpha Search v2")
    assert dialog.folder_edit.text() == "alpha"  # Typed once, the folder is the person's.
    dialog.deleteLater()
