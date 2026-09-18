"""Membership: File ▸ New Project… and Open Project…, the projects module's half.

Both dialogs are stood in for at the names the module reads, and the Open Project wizard
is also built for real over the running application's services — git runs, gh never does.
What is under test is everything around them: what gets seeded on disk, listed in the
index, attached to the store, added to the model, greyed as already here, or refused with
a reason. The wizard's two pages are tested through the wizard rather than on their own,
because which page is showing is half of what it does.
"""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog
from tests.facts import code_row

from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.provider import StorageError
from dplanner.domain.plan_repo import read_meta
from dplanner.domain.project_link import ProjectLink, document_text, encode
from dplanner.domain.seed import seed_project
from dplanner.domain.store import PROJECT_META
from dplanner.modules.projects import module as projects_module
from dplanner.modules.projects.open_dialog import (
    BROWSE,
    BROWSE_PAGE,
    CHOOSE,
    LINK,
    LINK_PAGE,
    OpenProjectDialog,
)
from dplanner.modules.projects.project_dialog import NewProjectSpec
from dplanner.modules.projects.repo_picker import PlanTarget
from dplanner.modules.projects.repos import Joined, shown_path
from dplanner.modules.projects.repositories_folder import set_repositories_folder


def run(services, action_id):
    services.actions.run(action_id, services.context.current())


def module(services):
    return next(m for m in services.modules if m.id == "projects")


def commit_all(root, author="Anna"):
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            f"user.name={author}",
            "-c",
            "user.email=a@example.com",
            "commit",
            "-qm",
            "plans",
        ],
        check=True,
    )


def inline(runner, monkeypatch):
    """Run a page's task bodies where they are called: a test asserts on the answer, and
    the thread is not what is under test here."""

    def run_now(_label, body, **_kwargs):
        body()
        return True

    monkeypatch.setattr(runner, "run", run_now)


def answering(joined):
    """Stands in for the wizard at the name the module reads; answers what the test set."""

    class Fake:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 1 if joined else 0

        def joined(self):
            return joined

        def deleteLater(self):  # noqa: N802 - Qt's name
            pass

    return Fake


# -- New Project… ------------------------------------------------------------------------------


@pytest.fixture
def create(monkeypatch):
    """Stands in for the Project dialog in create mode; answers the spec the test set."""
    answers: dict[str, NewProjectSpec | None] = {}

    class Fake:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 1 if answers.get("spec") is not None else 0

        def spec(self):
            return answers.get("spec")

        def deleteLater(self):  # noqa: N802 - Qt's name
            pass

    monkeypatch.setattr(projects_module, "ProjectDialog", Fake)
    return answers


def test_new_project_is_seeded_into_the_picked_plan_repository_and_connected(
    services, library_repo, tmp_path, create
):
    code = init_repo(tmp_path / "widget")
    create["spec"] = NewProjectSpec(
        title="Alpha Search",
        summary="Find things",
        plan=PlanTarget(library_repo),
        folder="alpha-search",
        locations=code_row("https://github.com/acme/widget"),
        checkouts=(("https://github.com/acme/widget", code),),
    )
    run(services, "projects.new")
    target = library_repo / "alpha-search"
    assert (target / PROJECT_META).is_file()
    assert (library_repo / ".dplanner").read_text().splitlines() == ["alpha-search"]
    (project,) = services.document.projects
    assert project.title == "Alpha Search" and project.summary == "Find things"
    assert project.locations == code_row("https://github.com/acme/widget")
    assert services.repo.project_dir(project.id) == target.resolve()
    assert services.repo.checkout_for("https://github.com/acme/widget") == code
    assert "created" in services.window.statusBar().currentMessage()


def test_new_project_initialises_a_new_local_plan_repository(services, tmp_path, create):
    create["spec"] = NewProjectSpec(
        title="Solo",
        summary="",
        plan=PlanTarget(tmp_path / "plans", init=True),
        folder="solo",
        locations=(),
    )
    run(services, "projects.new")
    assert (tmp_path / "plans" / ".git").is_dir()
    assert (tmp_path / "plans" / "solo" / PROJECT_META).is_file()
    assert [p.title for p in services.document.projects] == ["Solo"]


def test_new_project_on_github_publishes_the_fresh_repository(
    services, tmp_path, create, monkeypatch
):
    from dplanner.core.storage import github

    published = []
    monkeypatch.setattr(
        github.GitHubStorage,
        "publish",
        classmethod(lambda cls, storage, name, **_k: published.append((storage.repo_root, name))),
    )
    create["spec"] = NewProjectSpec(
        title="Solo",
        summary="",
        plan=PlanTarget(tmp_path / "plans", init=True, publish="plans"),
        folder="solo",
        locations=(),
    )
    run(services, "projects.new")
    assert published == [((tmp_path / "plans").resolve(), "plans")]
    # Published after a commit: gh refuses a repository with nothing to push.
    log = subprocess.run(
        ["git", "-C", str(tmp_path / "plans"), "log", "--oneline"], capture_output=True, text=True
    )
    assert "Start the plan repository" in log.stdout


def test_cancelling_new_project_creates_nothing(services, create):
    create["spec"] = None
    run(services, "projects.new")
    assert services.document.projects == []


# -- Open Project…: the wizard frame --------------------------------------------------------------


@pytest.fixture
def plans(tmp_path):
    """A plan repository two people worked on, with two projects in it."""
    root = init_repo(tmp_path / "plans")
    seed_project(root / "search", "Search")
    commit_all(root, "Anna")
    seed_project(root / "billing", "Billing")
    commit_all(root, "Bo")
    return root


def wizard(services, monkeypatch, *, listed_dirs=None, listed_ids=None, clone=None, checkout=None):
    """The wizard over the running application, wired as the module wires it — the library
    it already has is what the pages grey and refuse against, so a test that adds a project
    first sees it here too."""
    deps = module(services)._deps
    repos = deps.repos if clone is None else replace(deps.repos, clone=clone)
    dialog = OpenProjectDialog(
        repos,
        deps.tasks,
        deps.theme,
        listed_dirs=list(deps.project_dirs() if listed_dirs is None else listed_dirs),
        listed_ids=list(
            [p.id for p in services.document.projects] if listed_ids is None else listed_ids
        ),
        known_checkout=(lambda _remote: checkout),
        parent=services.window,
    )
    inline(dialog.browse._runner, monkeypatch)
    inline(dialog.link._runner, monkeypatch)
    return dialog


def test_the_wizard_opens_on_the_way_in_that_needs_no_library(services, monkeypatch):
    dialog = wizard(services, monkeypatch)
    assert dialog.current_page() == CHOOSE
    assert dialog.way() == LINK  # A link is what somebody joining for the first time has.
    assert dialog.primary_button.text() == "Continue"
    assert not dialog.back_button.isVisibleTo(dialog)
    dialog.deleteLater()


def test_continuing_shows_the_page_for_the_chosen_way_and_back_returns(services, monkeypatch):
    dialog = wizard(services, monkeypatch)
    dialog.ways.setCurrentRow(1)
    assert dialog.way() == BROWSE
    dialog.primary_button.click()
    assert dialog.current_page() == BROWSE_PAGE and dialog.back_button.isVisibleTo(dialog)
    dialog.back_button.click()
    assert dialog.current_page() == CHOOSE and not dialog.back_button.isVisibleTo(dialog)
    dialog.deleteLater()


def test_the_wizard_keeps_one_size_from_page_to_page(services, monkeypatch):
    """A Wayland compositor applies a shown window's resize at its next configure, so a
    wizard that resized per page drew each page clipped until focus moved."""
    dialog = wizard(services, monkeypatch)
    size = dialog.size()
    for page in (LINK_PAGE, BROWSE_PAGE, CHOOSE):
        dialog.show_page(page)
        assert dialog.size() == size
    dialog.deleteLater()


def test_the_way_last_used_is_the_one_the_next_wizard_opens_on(services, monkeypatch):
    first = wizard(services, monkeypatch)
    first.ways.setCurrentRow(1)
    first.primary_button.click()
    first.deleteLater()
    again = wizard(services, monkeypatch)
    assert again.way() == BROWSE
    again.deleteLater()


# -- Open Project… ▸ browse a plan repository ------------------------------------------------------


def browsing(services, monkeypatch, **kwargs):
    dialog = wizard(services, monkeypatch, **kwargs)
    dialog.ways.setCurrentRow(1)
    dialog.primary_button.click()
    return dialog


def test_browsing_lists_what_the_repository_holds_with_who_and_when(services, plans, monkeypatch):
    dialog = browsing(services, monkeypatch)
    page = dialog.browse
    assert page.empty.isVisibleTo(page) and not page.list.isVisibleTo(page)  # Nothing picked.
    page.picker.set_current(plans)
    assert page.rows() == [
        ("Search · 0 steps", "Anna, just now"),
        ("Billing · 0 steps", "Bo, just now"),
    ]
    # Every addable row starts selected: joining a plan repository means joining it.
    assert sorted(page.chosen()) == sorted([plans / "search", plans / "billing"])
    assert dialog.primary_button.text() == "Add 2 to Library" and dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_project_already_here_is_greyed_and_not_offered(services, plans, monkeypatch):
    dialog = browsing(services, monkeypatch, listed_dirs=[plans / "search"])
    dialog.browse.picker.set_current(plans)
    assert dialog.browse.rows()[0] == ("Search · 0 steps", "already in this library")
    assert dialog.browse.chosen() == [plans / "billing"]
    assert dialog.primary_button.text() == "Add to Library"
    dialog.deleteLater()


def test_the_same_plan_in_another_clone_is_greyed_by_its_id(services, plans, monkeypatch):
    dialog = browsing(services, monkeypatch, listed_ids=[read_meta(plans / "search")["id"]])
    dialog.browse.picker.set_current(plans)
    assert dialog.browse.rows()[0][1] == "already in this library"
    dialog.deleteLater()


def test_an_activity_answer_for_a_repository_the_page_left_is_dropped(
    services, plans, tmp_path, monkeypatch
):
    other = init_repo(tmp_path / "other")
    seed_project(other / "gadget", "Gadget")
    commit_all(other, "Cy")
    dialog = browsing(services, monkeypatch)
    page = dialog.browse
    pending = []

    def hold(_label, body, **_kwargs):
        pending.append(body)
        return True

    monkeypatch.setattr(page._runner, "run", hold)
    page.picker.set_current(plans)
    page.picker.set_current(other)
    pending[0]()  # The first repository's answer arrives after the page moved on.
    assert page.rows() == [("Gadget · 0 steps", "…")]
    pending[1]()
    assert page.rows() == [("Gadget · 0 steps", "Cy, just now")]
    dialog.deleteLater()


def test_browsing_to_a_folder_outside_git_is_refused_in_the_note(services, tmp_path, monkeypatch):
    loose = tmp_path / "loose"
    loose.mkdir()
    dialog = browsing(services, monkeypatch)
    picker = dialog.browse.picker
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(loose))
    browse = next(e for e in picker.entries() if e is not None and e.label == "Another folder…")
    browse.run()
    assert "not inside a git repository" in picker.note.words()
    assert picker.note.tone() == "error"
    assert picker.current() is None
    dialog.deleteLater()


def test_an_empty_repository_says_so_and_a_dangling_index_line_is_named(
    services, tmp_path, monkeypatch
):
    root = init_repo(tmp_path / "plans")
    (root / ".dplanner").write_text("gone\n")
    dialog = browsing(services, monkeypatch)
    page = dialog.browse
    page.picker.set_current(root)
    assert page.empty.isVisibleTo(page) and "No projects" in page.empty.text()
    assert page.note.isVisibleTo(page) and "gone" in page.note.text()
    assert not dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_adding_connects_the_chosen_projects_to_the_library(services, plans, monkeypatch):
    joined = [Joined(plans / "search"), Joined(plans / "billing")]
    monkeypatch.setattr(projects_module, "OpenProjectDialog", answering(joined))
    run(services, "projects.add")
    assert [p.title for p in services.document.projects] == ["Search", "Billing"]
    assert (
        services.repo.project_dir(services.document.projects[0].id) == (plans / "search").resolve()
    )
    assert "2 projects added" in services.window.statusBar().currentMessage()


# -- Open Project… ▸ open a project link ----------------------------------------------------------


@pytest.fixture
def shared(tmp_path):
    """A plan repository published somewhere, and the link to one project in it.

    The remote is a path rather than a URL because a test may not reach GitHub, and
    ``canonical_remote`` treats the two the same — which is the point: what a link names
    is a remote, whatever kind.
    """
    origin = init_repo(tmp_path / "origin" / "plans")
    seed_project(origin / "search", "Search", summary="Replace the index")
    commit_all(origin, "Anna")
    return origin, ProjectLink(
        plan_remote=str(origin),
        plan_path="search",
        project_id=read_meta(origin / "search")["id"],
        title="Search",
        summary="Replace the index",
        code_remote="https://github.com/acme/widget",
    )


def linking(services, monkeypatch, **kwargs):
    dialog = wizard(services, monkeypatch, **kwargs)
    dialog.primary_button.click()  # The link row leads.
    assert dialog.current_page() == LINK_PAGE
    return dialog


def cloner(tmp_path, recorded):
    """Stands in for gh: a clone is a git clone of a path, and what was asked is recorded."""

    def clone(remote, dest):
        recorded.append((remote, dest))
        subprocess.run(["git", "clone", "-q", str(remote), str(dest)], check=True)

    return clone


def test_a_pasted_link_says_what_it_names_and_where_the_plan_will_land(
    services, shared, monkeypatch
):
    _origin, link = shared
    dialog = linking(services, monkeypatch)
    dialog.link.set_text(encode(link))
    page = dialog.link
    assert page.found.isVisibleTo(page)
    assert page.project_line.text() == "Search"
    assert page.summary_line.text() == "Replace the index"
    assert "will be cloned into" in page.plan_where.text()
    assert dialog.primary_button.text() == "Set Up Project" and dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_link_file_is_read_the_same_as_a_pasted_one(services, shared, tmp_path, monkeypatch):
    _origin, link = shared
    path = tmp_path / link.filename
    path.write_text(document_text(link), encoding="utf-8")
    dialog = linking(services, monkeypatch)
    dialog.link.set_text(str(path))
    assert dialog.link.project_line.text() == "Search"
    dialog.deleteLater()


def test_something_that_is_not_a_link_is_refused_under_the_field(services, monkeypatch):
    dialog = linking(services, monkeypatch)
    dialog.link.set_text("https://github.com/acme/plans")
    page = dialog.link
    assert page.link_status.tone() == "error" and "not a dplanner" in page.link_status.words()
    assert not page.found.isVisibleTo(page)
    assert not dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_link_for_a_project_already_here_is_refused_by_name(services, shared, monkeypatch):
    _origin, link = shared
    dialog = linking(services, monkeypatch, listed_ids=[link.project_id])
    dialog.link.set_text(encode(link))
    assert dialog.link.refusal() == "“Search” is already in this library"
    assert not dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_plan_repository_this_machine_already_has_is_used_rather_than_cloned(
    services, shared, plans, tmp_path, monkeypatch
):
    origin, link = shared
    # The library's own plan repository is a clone of the link's remote, so there is
    # nothing to fetch: the wizard points straight at the project inside it.
    here = tmp_path / "here"
    subprocess.run(["git", "clone", "-q", str(origin), str(here)], check=True)
    module(services)._deps.connect_project(here / "search")
    recorded: list[tuple[str, Path]] = []
    dialog = linking(services, monkeypatch, clone=cloner(tmp_path, recorded))
    dialog.link.set_text(encode(link))
    assert dialog.link.plan_where.text() == f"already at {shown_path(here / 'search')}"
    assert dialog.link.refusal() == "“Search” is already in this library"
    assert recorded == []
    dialog.deleteLater()


def test_a_clone_without_the_project_the_link_names_says_to_pull(
    services, shared, tmp_path, monkeypatch
):
    origin, link = shared
    here = tmp_path / "here"
    subprocess.run(["git", "clone", "-q", str(origin), str(here)], check=True)
    module(services)._deps.connect_project(here / "search")
    moved = replace(link, plan_path="ranking", project_id="another", title="Ranking")
    dialog = linking(services, monkeypatch)
    dialog.link.set_text(encode(moved))
    assert "pull it and try again" in (dialog.link.refusal() or "")
    dialog.deleteLater()


def test_setting_up_clones_the_plan_and_answers_with_the_project_directory(
    services, shared, tmp_path, monkeypatch
):
    origin, link = shared
    set_repositories_folder(tmp_path / "Code")
    recorded: list[tuple[str, Path]] = []
    dialog = linking(services, monkeypatch, clone=cloner(tmp_path, recorded))
    dialog.link.set_text(encode(link))
    dialog.link.checkout_edit.clear()  # The code is somebody else's problem in this test.
    dialog.primary_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.joined() == [Joined(tmp_path / "Code" / "plans" / "search")]
    assert recorded == [(str(origin), tmp_path / "Code" / "plans")]
    dialog.deleteLater()


def test_setting_up_clones_the_code_into_the_folder_the_person_named(
    services, shared, tmp_path, monkeypatch
):
    origin, link = shared
    code_origin = init_repo(tmp_path / "origin" / "widget")
    (code_origin / "README.md").write_text("the widget\n")
    commit_all(code_origin, "Anna")
    link = replace(link, code_remote=str(code_origin))
    set_repositories_folder(tmp_path / "Code")
    recorded: list[tuple[str, Path]] = []
    dialog = linking(services, monkeypatch, clone=cloner(tmp_path, recorded))
    dialog.link.set_text(encode(link))
    assert dialog.link.checkout_edit.text() == str(tmp_path / "Code" / "widget")
    assert "will be cloned into" in dialog.link.checkout_where.text()
    dialog.primary_button.click()
    assert dialog.joined()[0].checkouts == ((str(code_origin), tmp_path / "Code" / "widget"),)
    assert (tmp_path / "Code" / "widget" / ".git").is_dir()
    assert [remote for remote, _dest in recorded] == [str(origin), str(code_origin)]
    dialog.deleteLater()


def test_setting_up_again_after_the_code_failed_uses_the_plan_it_already_cloned(
    services, shared, tmp_path, monkeypatch
):
    origin, link = shared
    set_repositories_folder(tmp_path / "Code")
    recorded: list[tuple[str, Path]] = []
    clone_plan = cloner(tmp_path, recorded)

    def clone(remote, dest):
        if remote == link.code_remote:
            raise StorageError("no access to acme/widget")
        clone_plan(remote, dest)

    dialog = linking(services, monkeypatch, clone=clone)
    dialog.link.set_text(encode(link))  # The checkout is offered in the folder, to be cloned.
    dialog.primary_button.click()
    assert dialog.link.link_status.words() == "no access to acme/widget"
    dialog.link.checkout_edit.clear()
    dialog.primary_button.click()
    assert dialog.joined() == [Joined(tmp_path / "Code" / "plans" / "search")]
    assert recorded == [(str(origin), tmp_path / "Code" / "plans")]  # Cloned once, not twice.
    dialog.deleteLater()


def test_a_checkout_this_machine_already_has_is_offered_rather_than_a_clone(
    services, shared, tmp_path, monkeypatch
):
    _origin, link = shared
    here = init_repo(tmp_path / "widget")
    dialog = linking(services, monkeypatch, checkout=here)
    dialog.link.set_text(encode(link))
    assert dialog.link.checkout_edit.text() == str(here)
    assert dialog.link.checkout_where.text() == "acme/widget, already there"
    dialog.deleteLater()


@pytest.mark.parametrize("taken", ["occupied", "occupied/notes.txt"])
def test_a_checkout_path_that_is_something_else_is_refused(
    services, shared, tmp_path, monkeypatch, taken
):
    """A folder of something else — or a file, which is no folder to look inside at all."""
    _origin, link = shared
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("mine")
    dialog = linking(services, monkeypatch)
    dialog.link.set_text(encode(link))
    dialog.link.checkout_edit.setText(str(tmp_path / taken))
    assert "is not a checkout" in (dialog.link.refusal() or "")
    assert not dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_link_naming_no_code_repository_leaves_the_checkout_alone(services, shared, monkeypatch):
    _origin, link = shared
    dialog = linking(services, monkeypatch)
    dialog.link.set_text(encode(replace(link, code_remote="")))
    assert not dialog.link.checkout_edit.isEnabled()
    assert dialog.link.checkout_where.text() == "this link names no code repository"
    assert dialog.primary_button.isEnabled()
    dialog.deleteLater()


def test_a_clone_that_fails_says_so_and_the_wizard_stays_open(
    services, shared, tmp_path, monkeypatch
):
    _origin, link = shared
    set_repositories_folder(tmp_path / "Code")

    def refuse(_remote, _dest):
        raise StorageError("gh is not signed in")

    dialog = linking(services, monkeypatch, clone=refuse)
    dialog.link.set_text(encode(link))
    dialog.link.checkout_edit.clear()
    dialog.primary_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted  # Nothing accepted it.
    assert dialog.link.link_status.words() == "gh is not signed in"
    assert dialog.joined() == []
    dialog.deleteLater()
