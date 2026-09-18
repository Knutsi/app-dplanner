"""The Project dialog and the Repositories card: where a project's plan and code live.

The dialog is built over a ``RepositoryServices`` of lambdas — git and gh never run — and
its task bodies are run inline, so what a worker thread would deliver arrives on the line
after the request. What is under test is everything around the fakes: what each column
says it is and where it is, what its ⋯ menu offers and why an entry is greyed, which verb
commits which fact through which path, and what the plan column offers while the plan has
no repository of its own.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog
from tests.facts import code_row

from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.sparse import Probe
from dplanner.domain.commands import AddNodeCommand, SetFieldCommand
from dplanner.domain.locations import CODE, Location, roles_by_id
from dplanner.domain.model import Step
from dplanner.domain.relocate import Moved
from dplanner.domain.repositories import ACCEPTED, repository_facts
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.dialog import LinePrompt
from dplanner.modules.projects import project_dialog
from dplanner.modules.projects import repositories_folder as folders
from dplanner.modules.projects.project_dialog import CREATE, ProjectDialog
from dplanner.modules.projects.repo_picker import menu_of
from dplanner.modules.projects.repos import (
    MOVE_PLAN,
    SET_UP_PLAN,
    LogEntry,
    PullRequest,
    RepoLog,
    RepositoryServices,
    candidate_repositories_folders,
    shown_path,
)
from dplanner.theme.tokens import CONTROL_HEIGHT

CODE_URL = "https://github.com/acme/widget"
INK = "#808080"  # A menu is painted in the ink its surface hands it; any will do here.


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
            library.project(project_id), store.project_dir(project_id), store.checkouts()
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
        roles=roles_by_id([CODE]),
        project_dir=store.project_dir,
        checkout_for=store.checkout_for,
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
        list_folders=lambda _url, ref: Probe(ref, ()),
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
    services.undo.push(SetFieldCommand(project.id, "locations", code_row(CODE_URL)))
    services.repo.set_checkout(CODE_URL, code)
    return code


# -- what each column says it is and where it is --------------------------------------------


def code_of(project):
    """The project's code repository as its table names it, "" for none."""
    return project.locations[0].repository if project.locations else ""


def entry(column, label):
    """One entry of a column's ⋯ menu, by its label — the menu is asked afresh, so this
    reads the state the user would see on opening it now."""
    return next(e for e in column.entries() if e is not None and e.label == label)


def labels(column):
    return [None if e is None else e.label for e in column.entries()]


def test_each_column_names_its_repository_and_where_it_is_here(
    services, dialog, project, tmp_path, library_repo
):
    """The two lines under a column are the whole answer to *which repository is this*
    and *where is it on this machine* — the same pair on both sides of the divide."""
    assert dialog.code_column.identity.text() == "no code repository recorded"
    assert dialog.code_column.location.text().endswith(library_repo.name)  # The older shape.
    assert dialog.plan_column.identity.text() == "repo"  # No origin yet: the folder.
    assert dialog.plan_column.location.text().endswith(library_repo.name)

    code = separate(services, project, tmp_path)
    assert dialog.code_column.identity.text() == "acme/widget"
    assert dialog.code_column.location.text().endswith(code.name)
    assert dialog.plan_column.location.text().endswith(library_repo.name)


def test_a_fact_nobody_recorded_is_said_and_greyed(services, dialog, project):
    assert dialog.code_column.identity.objectName() == "RepoLineMissing"
    services.undo.push(SetFieldCommand(project.id, "locations", code_row(CODE_URL)))
    assert dialog.code_column.identity.objectName() == "RepoIdentity"
    assert dialog.code_column.location.text() == "not checked out on this machine"
    assert dialog.code_column.location.objectName() == "RepoLineMissing"


# -- the ⋯ menus ------------------------------------------------------------------------------


def test_both_menus_keep_their_shape_and_grey_what_cannot_run(services, dialog, project):
    """DESIGN.md: an entry that exists but does not apply is greyed with the reason, never
    dropped — so the menu is the same list to learn whatever the project's state."""
    before = labels(dialog.code_column)
    assert entry(dialog.code_column, "Create on GitHub…").reason == ""
    assert entry(dialog.code_column, "Clone into Repositories Folder").reason == (
        "no code repository recorded"
    )
    assert entry(dialog.code_column, "Open on GitHub").reason == "not a GitHub repository"

    services.undo.push(SetFieldCommand(project.id, "locations", code_row(CODE_URL)))
    assert entry(dialog.code_column, "Open on GitHub").reason == ""
    assert entry(dialog.code_column, "Clone into Repositories Folder").reason == ""
    assert entry(dialog.code_column, "Create on GitHub…").reason == (
        "this project already records one"
    )
    # Nothing appeared and nothing went: only the reasons changed. (The plan column's
    # first entry is the exception, and it is worded by the offer, not by what exists.)
    assert labels(dialog.code_column) == before


def test_a_greyed_entry_carries_its_reason_in_its_words(dialog):
    assert entry(dialog.plan_column, "Open on GitHub").text == (
        "Open on GitHub — not a GitHub repository"
    )
    assert entry(dialog.plan_column, SET_UP_PLAN).text == SET_UP_PLAN


def test_the_move_entry_is_worded_as_the_offer_this_project_needs(
    services, dialog, project, tmp_path
):
    """One verb, two offers: a plan inside its code is being given a repository, a plan
    that has one is being moved to another — and the setup button says the same words."""
    assert dialog.plan_column.setup_button.text() == SET_UP_PLAN
    assert entry(dialog.plan_column, SET_UP_PLAN).reason == ""
    separate(services, project, tmp_path)
    assert entry(dialog.plan_column, MOVE_PLAN).reason == ""


def test_the_menu_renders_what_the_entries_say(dialog):
    """The pop-up is the entries, rendered: the greyed rows are the ones with a reason,
    the separator is there, and every row carries a glyph."""
    menu = menu_of(dialog.code_column.entries(), INK, dialog)
    try:
        rows = [
            (action.text(), action.isEnabled(), not action.icon().isNull())
            for action in menu.actions()
            if not action.isSeparator()
        ]
        assert [action.isSeparator() for action in menu.actions()].count(True) == 1
        assert rows[0] == ("Set Code Repository…", True, True)
        assert rows[1] == ("Pick from GitHub…", True, True)
        assert rows[2] == ("Open on GitHub — not a GitHub repository", False, True)
        assert all(icon for _text, _enabled, icon in rows)
    finally:
        menu.deleteLater()


def test_set_code_repository_commits_through_the_undo_stack(services, dialog, project, monkeypatch):
    asked = []

    def ask(*args, **kwargs):
        asked.append((args, kwargs))
        return CODE_URL

    monkeypatch.setattr(LinePrompt, "ask", staticmethod(ask))
    entry(dialog.code_column, "Set Code Repository…").run()
    # A LinePrompt named for its verb, seeded with what is recorded (DESIGN.md's *Dialogs*).
    assert asked[0][0][1:4] == (
        "Code Repository",
        "The code this plan is about, as git names it",
        "Set",
    )
    assert code_of(services.document.project(project.id)) == CODE_URL
    assert services.undo.undo_text() == "Change Locations"
    services.undo.undo()
    assert code_of(services.document.project(project.id)) == ""
    assert dialog.code_column.identity.text() == "no code repository recorded"


def test_choosing_a_checkout_records_it_in_the_library_file_not_the_undo_stack(
    services, dialog, project, tmp_path, monkeypatch
):
    code = init_repo(tmp_path / "widget")  # No origin: nothing but the checkout is learnt.
    services.autosave.flush_now()
    before = services.undo.undo_text()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(code))
    entry(dialog.code_column, "Choose Checkout…").run()
    # No repository recorded and no origin: filed under the folder's own path, which is
    # the only identity a repository that cannot be shared has.
    assert services.repo.checkout_for(str(code)) == code
    assert services.undo.undo_text() == before
    assert not services.autosave.has_pending()  # Written directly, nothing left to flush.


def test_a_chosen_checkout_fills_an_empty_code_repository_from_its_origin(
    services, dialog, project, tmp_path, monkeypatch
):
    import subprocess

    code = init_repo(tmp_path / "widget")
    subprocess.run(["git", "-C", str(code), "remote", "add", "origin", CODE_URL], check=True)
    (code / "src").mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(code / "src"))
    entry(dialog.code_column, "Choose Checkout…").run()
    assert services.repo.checkout_for(CODE_URL) == code  # The repository root, not src/.
    assert code_of(services.document.project(project.id)) == CODE_URL


def test_keep_it_here_accepts_the_colocation_and_quiets_the_warning(services, dialog, project):
    assert dialog.warning_row.isVisibleTo(dialog)
    assert dialog.plan_column.setup_button.objectName() == "PrimaryButton"
    dialog.keep_button.click()
    assert services.document.project(project.id).colocation == ACCEPTED
    assert not dialog.warning_row.isVisibleTo(dialog)
    assert dialog.plan_column.setup_button.objectName() == "PlanSetupButton"  # Quiet now.
    assert dialog.plan_column.setup_button.isVisibleTo(dialog)


def test_the_setup_button_and_the_plan_menu_both_open_the_move_wizard(dialog, project):
    dialog.plan_column.setup_button.click()
    entry(dialog.plan_column, SET_UP_PLAN).run()
    assert dialog.moved == [project.id, project.id]


# -- the logs -----------------------------------------------------------------------------------


def test_a_plan_beside_its_code_shows_one_log_and_offers_setup(dialog, fakes, library_repo):
    _repos, calls, _state = fakes
    assert calls["history"] == [(library_repo, "")]  # The plan's repository is the code's.
    assert dialog.code_column.rows() == [("Add the login form", "anna · just now")]
    assert dialog.code_column.branch.text() == "main"
    assert dialog.plan_column.setup_button.isVisibleTo(dialog)
    assert not dialog.plan_column.well.isVisibleTo(dialog)


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
    assert dialog.plan_column.well.isVisibleTo(dialog)
    assert not dialog.plan_column.empty.isVisibleTo(dialog)
    assert not dialog.warning_row.isVisibleTo(dialog)
    # A plan already apart from its code is still moved from here: the offer that put it
    # on the wrong repository is the one that has to be able to put it right.
    assert entry(dialog.plan_column, MOVE_PLAN).reason == ""


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
    services.undo.push(SetFieldCommand(project.id, "locations", code_row(CODE_URL)))
    assert dialog.code_column.rows() == [("#7 Build the modal", "S1 Read the spec · feat/login")]
    state["prs"] = []
    dialog.show_project(project.id)
    assert dialog.code_column.empty.isVisibleTo(dialog)
    assert not dialog.code_column.well.isVisibleTo(dialog)
    assert "Not checked out" in dialog.code_column.empty.text()


# -- gh ---------------------------------------------------------------------------------------


def test_without_gh_every_entry_that_needs_it_is_greyed_and_the_note_says_why(
    services, fakes, project, dialog
):
    _repos, _calls, state = fakes
    state["gh"] = "gh not found on PATH — GitHub features need the GitHub CLI"
    dialog.show_project(project.id)
    assert dialog.gh_note.isVisibleTo(dialog) and "gh not found" in dialog.gh_note.text()
    for column, label in (
        (dialog.code_column, "Create on GitHub…"),
        (dialog.code_column, "Clone into Repositories Folder"),
        (dialog.plan_column, "Publish to GitHub…"),
    ):
        assert "gh not found" in entry(column, label).reason
    state["gh"] = None
    dialog.show_project(project.id)
    assert not dialog.gh_note.isVisibleTo(dialog)
    assert entry(dialog.code_column, "Create on GitHub…").reason == ""  # No repository yet.


def test_clone_lands_in_the_repositories_folder_and_records_the_checkout(
    services, fakes, dialog, project, tmp_path
):
    _repos, calls, _state = fakes
    folders.set_repositories_folder(tmp_path / "Code")
    services.undo.push(SetFieldCommand(project.id, "locations", code_row(CODE_URL)))
    entry(dialog.code_column, "Clone into Repositories Folder").run()
    assert calls["clone"] == [(CODE_URL, tmp_path / "Code" / "widget")]
    assert services.repo.checkout_for(CODE_URL) == tmp_path / "Code" / "widget"
    assert "Cloned into" in dialog.status.words() and dialog.status.tone() == "ok"


def test_a_new_code_repository_is_created_cloned_and_recorded(
    services, fakes, dialog, project, tmp_path, monkeypatch
):
    _repos, calls, _state = fakes
    folders.set_repositories_folder(tmp_path / "Code")
    monkeypatch.setattr(LinePrompt, "ask", staticmethod(lambda *a, **k: "widget"))
    entry(dialog.code_column, "Create on GitHub…").run()
    assert calls["create"] == [("widget", tmp_path / "Code" / "widget")]
    assert code_of(services.document.project(project.id)) == "https://github.com/acme/widget"
    assert (
        services.repo.checkout_for("https://github.com/acme/widget") == tmp_path / "Code" / "widget"
    )


def test_publish_runs_for_a_plan_repository_without_an_origin_and_is_greyed_after(
    services, fakes, dialog, project, library_repo, monkeypatch
):
    import subprocess

    _repos, calls, _state = fakes
    assert entry(dialog.plan_column, "Publish to GitHub…").reason == ""
    monkeypatch.setattr(LinePrompt, "ask", staticmethod(lambda *a, **k: "plans"))
    entry(dialog.plan_column, "Publish to GitHub…").run()
    assert calls["publish"] == [(library_repo, "plans")]
    assert "Published as acme/plans" in dialog.status.words()

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
    assert entry(dialog.plan_column, "Publish to GitHub…").reason == "already published"
    assert dialog.plan_column.identity.text() == "acme/plans"


# -- the card -------------------------------------------------------------------------------


def _card(services, project):
    from dplanner.modules.project_dashboard.activity import DASHBOARD_KIND

    page = services.tabs.open(DASHBOARD_KIND, project.id).page
    return next(c for c in page.cards if c.title.text() == "Repositories").body


def test_the_card_states_the_plan_and_every_location_and_follows_the_facts(
    services, project, tmp_path, library_repo
):
    card = _card(services, project)
    assert card.plan_text.text() == "repo"  # The plan repository's folder: no origin yet.
    assert card.texts() == ["no code repository recorded"]
    assert card.note.isVisibleTo(card) and "inside the code" in card.note.text()
    assert card.move_button.text() == SET_UP_PLAN

    code = separate(services, project, tmp_path)
    assert card.texts() == [f"Code: acme/widget — {shown_path(code)}"]
    assert not card.note.isVisibleTo(card)
    # Apart from its code there is nothing to set *up* — but a plan repository picked
    # wrongly is still moved, and the button says which offer this is.
    assert card.move_button.text() == MOVE_PLAN
    # Every row the project names, worded once for the card and the dialog's table.
    rows = (
        *code_row(CODE_URL),
        Location("l2", "reporting", CODE_URL, path="reports/search"),
        Location("l3", "spec", "https://github.com/acme/specs", path="products"),
    )
    services.undo.push(SetFieldCommand(project.id, "locations", rows))
    assert card.texts() == [
        f"Code: acme/widget — {shown_path(code)}",
        f"Reporting: acme/widget · reports/search/ — {shown_path(code / 'reports' / 'search')}",
        "Spec: acme/specs · products/ — fetched on demand — not fetched yet",
    ]


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


def creating(services, fakes, monkeypatch=None):
    """*File ▸ New Project…*: the same dialog in create mode, wired as the module wires it
    — over the library it already has. Built by the test rather than by a fixture,
    because what the library holds when the dialog opens is half of what these tests are
    about."""
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
    if monkeypatch is not None:
        inline(dialog, monkeypatch)
    return dialog


def listing(repo, asked):
    """Stands in for the GitHub listing at the name the dialog reads; answers one
    repository and records how it was asked for."""

    class Fake:
        def __init__(self, _services, _tasks, _parent=None, *, title="", verb=""):
            asked.update(title=title, verb=verb)

        def exec(self):
            return 1

        def chosen(self):
            return repo

        def deleteLater(self):  # noqa: N802 - Qt's name
            pass

    return Fake


def answering(monkeypatch, **fields):
    """Stands in for the location dialog: fills the fields it is given, accepts."""
    from dplanner.modules.projects import location_dialog

    opened: list[dict[str, object]] = []

    class Fake(location_dialog.LocationDialog):
        def exec(self):
            opened.append(
                {
                    "role": self._role.id,
                    "repository": self.repository.currentText(),
                    "position": self.position.text(),
                    "repositories": [
                        self.repository.itemText(row) for row in range(self.repository.count())
                    ],
                }
            )
            if "repository" in fields:
                self.repository.setEditText(fields["repository"])
            if "position" in fields:
                self.position.setText(fields["position"])
            if "label" in fields:
                self.label.setText(fields["label"])
            return 1

    monkeypatch.setattr(project_dialog, "LocationDialog", Fake)
    return opened


def test_create_mode_answers_a_spec_once_a_name_and_a_home_are_given(
    services, fakes, tmp_path, monkeypatch
):
    """The same dialog, nothing to edit: a name, a plan repository, a folder — the folder
    follows the name until it is typed in — and the locations table over a draft."""
    dialog = creating(services, fakes)
    assert dialog.plan_picker is not None and dialog.folder_edit is not None
    assert not dialog.create_button.isEnabled()
    assert dialog.status.words() == "Name the project first"
    # A form, not a surface with menus: nothing exists yet to read a log of or act on.
    assert not dialog.code_column.isVisibleTo(dialog)
    assert dialog.locations.rows() == []

    dialog.name_edit.setText("Alpha Search")
    assert dialog.folder_edit.text() == "alpha-search"
    assert dialog.status.words() == "Pick a plan repository"  # The next thing missing.
    plans = init_repo(tmp_path / "plans")
    dialog.plan_picker.set_current(plans)
    assert dialog.create_button.isEnabled() and dialog.status.words() == ""

    opened = answering(monkeypatch, repository=CODE_URL)
    dialog.locations.add_requested.emit("code")
    assert opened[0]["role"] == "code"
    assert dialog.locations.rows() == [
        ("Code", "acme/widget", "", "not checked out on this machine")
    ]
    spec = dialog.spec()
    assert spec is not None
    assert spec.target == plans / "alpha-search" and spec.plan.root == plans
    assert spec.title == "Alpha Search" and spec.locations == code_row(CODE_URL)
    assert spec.checkouts == () and spec.repository == CODE_URL
    assert services.document.projects == []  # The dialog wrote nothing anywhere.

    (plans / "alpha").mkdir()
    dialog.folder_edit.setText("alpha")
    dialog.folder_edit.textEdited.emit("alpha")
    assert not dialog.create_button.isEnabled()
    assert dialog.status.words() == "A project already exists at that folder"
    assert dialog.target_label.text().endswith("alpha")  # The path, and only the path.
    dialog.name_edit.setText("Alpha Search v2")
    assert dialog.folder_edit.text() == "alpha"  # Typed once, the folder is the person's.
    dialog.deleteLater()


def test_the_settings_dialog_carries_close_alone_and_create_mode_a_primary(services, fakes, dialog):
    """DESIGN.md's *Dialogs*: every edit here is live, so the footer is one way out; New
    Project is a form with an answer, so it has Create and Cancel."""
    from dplanner.framework.dialog import DialogFrame

    assert isinstance(dialog, DialogFrame) and dialog.primary() is None
    assert [b.text() for b in dialog.footer_buttons()] == ["Close"]
    new = creating(services, fakes)
    try:
        assert new.windowTitle() == "New Project"
        assert [b.text() for b in new.footer_buttons()] == ["Create", "Cancel"]
        assert new.create_button.isDefault()
        assert not new.plan_column.isVisibleTo(new)
    finally:
        new.deleteLater()


def test_the_picker_offers_the_other_ways_in_as_one_menu(services, fakes, dialog):
    """Four glyph buttons became one ⋯ (DESIGN.md's *Buttons*): the same list in every
    dialog that asks, an entry greyed with its reason rather than dropped."""
    new = creating(services, fakes)
    try:
        picker = new.plan_picker
        assert picker is not None
        assert labels(picker) == [
            "Another folder…",
            "Clone from GitHub…",
            None,
            "New repository here…",
            "New repository on GitHub…",
        ]
        picker._cloning = True
        assert entry(picker, "Clone from GitHub…").reason == "a clone is still running"
        menu = menu_of(picker.entries(), INK, new)
        try:
            assert [a.isSeparator() for a in menu.actions()].count(True) == 1
        finally:
            menu.deleteLater()
    finally:
        new.deleteLater()


def test_the_add_menu_renders_the_role_registry(services, fakes):
    """A module declares a role and the entry appears: the Add ▾ is the registry, in its
    order, each role's glyph beside it."""
    new = creating(services, fakes)
    try:
        assert [entry.label for entry in new.locations.add_entries() if entry is not None] == [
            "Code…"
        ]
    finally:
        new.deleteLater()


def test_the_location_dialog_lists_what_this_library_already_names_the_code_first(
    services, fakes, project, tmp_path, monkeypatch
):
    """A second plan for code somebody here already works on is the common case, so the
    dialog's combo lists it — and the code the draft already names leads, because docs
    and tests live with the code more often than not."""
    separate(services, project, tmp_path)
    new = creating(services, fakes)
    try:
        opened = answering(monkeypatch)
        new.locations.add_requested.emit("code")
        assert opened[0]["repositories"] == [CODE_URL]
        assert opened[0]["repository"] == CODE_URL  # Pre-filled: the first entry.
        assert new.locations.rows()[0][1] == "acme/widget"
        # The checkout this machine already has for it comes along — a team's second
        # plan for one repository needs no second clone.
        assert new.locations.rows()[0][3].endswith("widget")
    finally:
        new.deleteLater()


def test_a_row_is_edited_by_activating_it_and_removed_from_its_menu(services, fakes, monkeypatch):
    new = creating(services, fakes)
    try:
        answering(monkeypatch, repository=CODE_URL)
        new.locations.add_requested.emit("code")
        answering(monkeypatch, repository="https://github.com/acme/ui", label="UI")
        new.locations.activated.emit("l1")
        assert new.locations.rows() == [
            ("Code — UI", "acme/ui", "", "not checked out on this machine")
        ]
        entries = new._location_entries(new._rows()[0])
        assert [entry.label for entry in entries if entry is not None] == [
            "Edit Location…",
            "Choose Checkout…",
            "Clone into Repositories Folder",
            "Open on GitHub",
            "Remove Location",
        ]
        entries[-1].run()
        assert (new.locations.rows() == [] and new.spec() is None) or new._draft == []
    finally:
        new.deleteLater()


def test_cloning_a_location_in_create_mode_lands_in_the_draft_and_writes_nothing(
    services, fakes, tmp_path, monkeypatch
):
    """A row's own verb, answered into the draft: there is no project yet to record a
    checkout onto, so the clone lands in what Create reads."""
    _repos, calls, _state = fakes
    folders.set_repositories_folder(tmp_path / "Code")
    new = creating(services, fakes, monkeypatch)
    try:
        answering(monkeypatch, repository=CODE_URL)
        new.locations.add_requested.emit("code")
        entries = new._location_entries(new._rows()[0])
        clone = next(entry for entry in entries if entry is not None and "Clone" in entry.label)
        assert clone.reason == ""
        clone.run()
        assert calls["clone"] == [(CODE_URL, tmp_path / "Code" / "widget")]
        spec = new.spec()
        assert spec is None or spec.checkouts == ((CODE_URL, tmp_path / "Code" / "widget"),)
        assert new.locations.rows()[0][3] == shown_path(tmp_path / "Code" / "widget")
        assert services.document.projects == []  # Nothing reached the library.
        assert new._location_entries(new._rows()[0])[3].reason == "already checked out here"
    finally:
        new.deleteLater()


def test_a_chosen_checkout_that_disagrees_with_the_named_code_is_asked_about(
    services, fakes, tmp_path, monkeypatch, dialog, project
):
    """Choose Checkout… on the code column: keeping either answer silently would leave
    the repository and the checkout naming different code."""
    import subprocess

    code = init_repo(tmp_path / "widget")
    subprocess.run(["git", "-C", str(code), "remote", "add", "origin", CODE_URL], check=True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(code))
    asked: list[str] = []

    def refuse(_parent, _title, question, **_kwargs):
        asked.append(question)
        return False

    monkeypatch.setattr(project_dialog, "confirm", refuse)
    services.undo.push(
        SetFieldCommand(project.id, "locations", code_row("https://github.com/acme/other"))
    )
    entry(dialog.code_column, "Choose Checkout…").run()
    assert services.repo.checkout_for("https://github.com/acme/other") == code
    assert len(asked) == 1 and CODE_URL in asked[0]
    assert code_of(services.document.project(project.id)) == "https://github.com/acme/other"


def test_a_glyph_button_stands_as_tall_as_the_field_it_is_beside(services, fakes):
    """DESIGN.md's *Forms*: the controls of one row are one height — the ⋯ beside the plan
    repository stood nine pixels short of the combo box it belongs to."""
    new = creating(services, fakes)
    try:
        new.show()
        field, button = new.plan_picker.combo, new.plan_picker.menu_button
        assert field.height() == button.height() == CONTROL_HEIGHT
        assert new.locations.add_button.height() == CONTROL_HEIGHT
    finally:
        new.deleteLater()


# -- the words, and what the wizard asks about ----------------------------------------------------


def test_a_location_is_worded_once_for_the_table_the_card_and_the_verbs(tmp_path):
    from dplanner.domain.locations import Location, Placement
    from dplanner.modules.projects.repos import location_words

    roles = roles_by_id([CODE])
    row = Location("l1", CODE.id, "git@github.com:Acme/Widget.git", path="apps/web", label="UI")
    here = location_words(Placement(row, tmp_path / "widget"), roles)
    assert (here.name, here.repository, here.position) == ("Code — UI", "Acme/Widget", "apps/web/")
    assert here.where == shown_path(tmp_path / "widget" / "apps" / "web") and not here.missing
    assert here.identity == "Code — UI: Acme/Widget · apps/web/"
    gone = location_words(Placement(row, None), roles)
    assert gone.where == "not checked out on this machine" and gone.missing
    cache = location_words(Placement(row, tmp_path / "cache", managed=True), roles)
    assert cache.where == "fetched on demand — not fetched yet" and cache.missing


def test_the_wizard_asks_only_about_worked_in_repositories_the_machine_lacks(tmp_path):
    from dplanner.domain.locations import Location, LocationRole
    from dplanner.modules.projects.repositories_page import missing_repositories

    roles = roles_by_id(
        [
            CODE,
            LocationRole("spec", "Spec", "", writes=False),
            LocationRole("reporting", "Reporting", "", writes=True),
        ]
    )
    rows = [
        Location("l1", "code", "https://github.com/acme/widget"),
        Location("l2", "reporting", "git@github.com:acme/widget.git", path="reports"),
        Location("l3", "spec", "https://github.com/acme/specs"),
        Location("l4", "code", "https://github.com/acme/ui", label="UI"),
        Location("l5", "wiki", "https://github.com/acme/wiki"),  # A role this build lacks.
    ]
    have = {"github.com/acme/ui": tmp_path / "ui"}
    missing = missing_repositories(
        rows, roles, lambda url: have.get(Location("x", "code", url).canonical)
    )
    assert [(entry.repository, [row.id for row in entry.locations]) for entry in missing] == [
        ("https://github.com/acme/widget", ["l1", "l2"])
    ]


# -- the location dialog ------------------------------------------------------------------------


def location_dialog(services, fakes, monkeypatch, *, repositories=(CODE_URL,), checkout_for=None):
    """The dialog for a new code row, its task bodies captured rather than run, so a test
    sees the arc turning and then delivers the answer itself."""
    from dplanner.domain.locations import CODE, next_id
    from dplanner.modules.projects.location_dialog import LocationDialog

    repos, _calls, _state = fakes
    bodies: list[Callable[[], None]] = []
    recorded: list[tuple[str, Path]] = []
    built = LocationDialog(
        CODE,
        location_id=next_id(()),
        repositories=list(repositories),
        location=None,
        checkout_for=checkout_for or (lambda _url: None),
        record_checkout=lambda repository, root: recorded.append((repository, root)),
        services=repos,
        tasks=services.tasks,
        theme=services.theme,
        parent=services.window,
    )

    def capture(_label, body, **_kwargs):
        bodies.append(body)
        return True

    monkeypatch.setattr(built._runner, "run", capture)
    return built, bodies, recorded


def test_the_location_dialog_lists_the_repositories_gh_knows_under_a_turning_refresh(
    services, fakes, monkeypatch
):
    """What the project and the library name leads; what gh knows follows after a
    separator, listed on a task the first time the dialog is seen and again on the refresh
    glyph, whose arc turns meanwhile. A refill never eats what is being typed, and gh
    refusing is a line under the row in the information tone, not an error."""
    _repos, _calls, state = fakes
    dialog, bodies, _recorded = location_dialog(services, fakes, monkeypatch)
    try:
        assert dialog.github_entries() == [CODE_URL] and bodies == []  # Not shown yet.
        dialog.show()
        assert len(bodies) == 1 and dialog.spinner.is_spinning()
        assert not dialog.refresh_button.isEnabled()
        assert dialog.listing_status.tone() == "busy"
        dialog.repository.setEditText("https://example.com/half-typ")
        bodies[0]()
        assert not dialog.spinner.is_spinning() and dialog.refresh_button.isEnabled()
        assert dialog.github_entries() == [CODE_URL, "https://github.com/acme/plans"]
        assert dialog.repository.currentText() == "https://example.com/half-typ"
        assert dialog.listing_status.words() == "2 repositories on GitHub"
        dialog.hide()
        dialog.show()
        assert len(bodies) == 1  # Once per dialog: the glyph is the way to ask again.

        state["gh"] = "gh is not installed"
        dialog.refresh_button.click()
        assert len(bodies) == 2 and dialog.spinner.is_spinning()
        bodies[1]()
        assert dialog.listing_status.words() == "gh is not installed"
        assert dialog.listing_status.tone() == "info"
        assert dialog.github_entries() == [CODE_URL]
        # The ⋯ offers one more way in, and the GitHub picker is no longer among them.
        assert [entry.label for entry in dialog._repository_entries() if entry] == [
            "From a folder on this computer…"
        ]
    finally:
        dialog.deleteLater()


def test_a_folder_on_this_computer_fills_the_row_and_records_the_checkout(
    services, fakes, tmp_path, monkeypatch
):
    """The spec author's way in: a folder of a checkout says the repository and the
    position, and the checkout is recorded for this machine — no Settings, no clone."""
    import subprocess

    repo = init_repo(tmp_path / "specs")
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", CODE_URL], check=True)
    (repo / "products" / "search").mkdir(parents=True)
    dialog, _bodies, recorded = location_dialog(services, fakes, monkeypatch, repositories=())
    try:
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(repo / "products" / "search")
        )
        dialog._from_folder()
        assert dialog.repository.currentText() == CODE_URL
        assert dialog.position.text() == "products/search"
        assert recorded == [(CODE_URL, repo)]
        assert dialog.listing_status.tone() == "ok"
        assert dialog.answer().path == "products/search" and dialog.primary().isEnabled()

        (tmp_path / "loose").mkdir()
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path / "loose")
        )
        dialog._from_folder()
        assert "not inside a git repository" in dialog.status.words()
        assert dialog.repository.currentText() == CODE_URL and len(recorded) == 1
    finally:
        dialog.deleteLater()


def test_the_position_is_browsed_in_the_checkout_when_this_machine_has_one(
    services, fakes, tmp_path, monkeypatch
):
    repo = init_repo(tmp_path / "widget")
    (repo / "apps" / "web").mkdir(parents=True)
    dialog, _bodies, _recorded = location_dialog(
        services, fakes, monkeypatch, checkout_for=lambda _url: repo
    )
    try:
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(repo / "apps" / "web")
        )
        dialog.folders_button.click()
        assert dialog.position.text() == "apps/web"
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path / "elsewhere")
        )
        dialog.folders_button.click()
        assert dialog.position.text() == "apps/web" and "outside" in dialog.status.words()
    finally:
        dialog.deleteLater()


def test_the_remote_folders_are_a_tree_and_nothing_is_cloned_to_pick_one(
    services, fakes, monkeypatch
):
    """Without a checkout the position is picked from the remote's listing — the git
    spec source's probe — shown as a tree, its first two levels open."""
    from dataclasses import replace

    from dplanner.core.storage.sparse import Folder
    from dplanner.framework.task_runner import TaskRunner
    from dplanner.modules.projects import location_dialog as module

    repos, calls, _state = fakes
    listing = Probe(
        "HEAD",
        (
            Folder("", 40, 0),
            Folder("docs", 20, 0),
            Folder("docs/api", 5, 0),
            Folder("docs/api/v2", 2, 0),
            Folder("src", 15, 0),
        ),
    )
    monkeypatch.setattr(TaskRunner, "run", lambda _self, _label, body, **_k: body() or True)
    dialog = module.RemoteFoldersDialog(
        replace(repos, list_folders=lambda _url, _ref: listing),
        services.tasks,
        CODE_URL,
        "HEAD",
        parent=services.window,
    )
    try:
        assert dialog.tree.topLevelItemCount() == 1
        root = dialog.tree.topLevelItem(0)
        assert root is not None
        children = [root.child(i) for i in range(root.childCount())]
        assert [child.text(0) for child in children if child is not None] == ["docs", "src"]
        docs = children[0]
        api = docs.child(0) if docs is not None else None
        v2 = api.child(0) if api is not None else None
        assert docs is not None and api is not None and v2 is not None
        assert root.isExpanded() and docs.isExpanded() and not api.isExpanded()
        assert dialog.chosen() == ""  # The root is current first.
        dialog.tree.setCurrentItem(v2)
        assert dialog.chosen() == "docs/api/v2"
        assert dialog.status.words() == "5 folders at HEAD"
        assert calls["clone"] == []
    finally:
        dialog.deleteLater()
