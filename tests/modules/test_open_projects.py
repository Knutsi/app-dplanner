"""Membership: File ▸ New Project… and Open Projects…, the projects module's half.

Both dialogs are stood in for at the names the module reads, and the Open Projects
dialog is also built for real over the running application's services — git runs, gh
never does. What is under test is everything around them: what gets seeded on disk,
listed in the index, attached to the store, added to the model, greyed as already here,
or refused with a reason.
"""

import subprocess

import pytest
from PySide6.QtWidgets import QFileDialog

from dplanner.core.storage.locations import init_repo
from dplanner.domain.seed import seed_project
from dplanner.domain.store import PROJECT_META
from dplanner.modules.projects import module as projects_module
from dplanner.modules.projects.open_dialog import OpenProjectsDialog
from dplanner.modules.projects.repo_picker import PlanTarget
from dplanner.modules.projects.settings_dialog import NewProjectSpec


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


def inline(dialog, monkeypatch):
    def run_now(_label, body, **_kwargs):
        body()
        return True

    monkeypatch.setattr(dialog._runner, "run", run_now)


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
        repository="https://github.com/acme/widget",
        checkout=code,
    )
    run(services, "projects.new")
    target = library_repo / "alpha-search"
    assert (target / PROJECT_META).is_file()
    assert (library_repo / ".dplanner").read_text().splitlines() == ["alpha-search"]
    (project,) = services.document.projects
    assert project.title == "Alpha Search" and project.summary == "Find things"
    assert project.repository == "https://github.com/acme/widget"
    assert services.repo.project_dir(project.id) == target.resolve()
    assert services.repo.checkout_of(project.id) == code
    assert "created" in services.window.statusBar().currentMessage()


def test_new_project_initialises_a_new_local_plan_repository(services, tmp_path, create):
    create["spec"] = NewProjectSpec(
        title="Solo",
        summary="",
        plan=PlanTarget(tmp_path / "plans", init=True),
        folder="solo",
        repository="",
        checkout=None,
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
        repository="",
        checkout=None,
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


# -- Open Projects… ----------------------------------------------------------------------------


@pytest.fixture
def plans(tmp_path):
    """A plan repository two people worked on, with two projects in it."""
    root = init_repo(tmp_path / "plans")
    seed_project(root / "search", "Search")
    commit_all(root, "Anna")
    seed_project(root / "billing", "Billing")
    commit_all(root, "Bo")
    return root


def open_dialog(services, monkeypatch, *, listed_dirs=(), listed_ids=()):
    deps = module(services)._deps
    dialog = OpenProjectsDialog(
        deps.repos,
        deps.tasks,
        deps.theme,
        listed_dirs=list(listed_dirs),
        listed_ids=list(listed_ids),
        parent=services.window,
    )
    inline(dialog, monkeypatch)
    return dialog


def test_open_projects_lists_what_the_repository_holds_with_who_and_when(
    services, plans, monkeypatch
):
    dialog = open_dialog(services, monkeypatch)
    assert dialog.pages.currentWidget() is dialog.empty  # Nothing picked yet.
    dialog.picker.set_current(plans)
    assert dialog.rows() == [
        ("Search · 0 steps", "Anna, just now"),
        ("Billing · 0 steps", "Bo, just now"),
    ]
    # Every addable row starts selected: joining a plan repository means joining it.
    assert sorted(dialog.chosen()) == sorted([plans / "search", plans / "billing"])
    assert dialog.add_button.text() == "Add 2 to Library" and dialog.add_button.isEnabled()
    dialog.deleteLater()


def test_a_project_already_here_is_greyed_and_not_offered(services, plans, monkeypatch):
    dialog = open_dialog(services, monkeypatch, listed_dirs=[plans / "search"])
    dialog.picker.set_current(plans)
    assert dialog.rows()[0] == ("Search · 0 steps", "already in this library")
    assert dialog.chosen() == [plans / "billing"]
    assert dialog.add_button.text() == "Add to Library"
    dialog.deleteLater()


def test_the_same_plan_in_another_clone_is_greyed_by_its_id(services, plans, monkeypatch):
    from dplanner.domain.plan_repo import read_meta

    search_id = read_meta(plans / "search")["id"]
    dialog = open_dialog(services, monkeypatch, listed_ids=[search_id])
    dialog.picker.set_current(plans)
    assert dialog.rows()[0][1] == "already in this library"
    dialog.deleteLater()


def test_an_activity_answer_for_a_repository_the_dialog_left_is_dropped(
    services, plans, tmp_path, monkeypatch
):
    other = init_repo(tmp_path / "other")
    seed_project(other / "gadget", "Gadget")
    commit_all(other, "Cy")
    dialog = open_dialog(services, monkeypatch)
    pending = []

    def hold(_label, body, **_kwargs):
        pending.append(body)
        return True

    monkeypatch.setattr(dialog._runner, "run", hold)
    dialog.picker.set_current(plans)
    dialog.picker.set_current(other)
    pending[0]()  # The first repository's answer arrives after the dialog moved on.
    assert dialog.rows() == [("Gadget · 0 steps", "…")]
    pending[1]()
    assert dialog.rows() == [("Gadget · 0 steps", "Cy, just now")]
    dialog.deleteLater()


def test_browsing_to_a_folder_outside_git_is_refused_in_the_note(services, tmp_path, monkeypatch):
    loose = tmp_path / "loose"
    loose.mkdir()
    dialog = open_dialog(services, monkeypatch)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(loose))
    dialog.picker.browse_button.click()
    assert "not inside a git repository" in dialog.picker.note.text()
    assert dialog.picker.current() is None
    dialog.deleteLater()


def test_an_empty_repository_says_so_and_a_dangling_index_line_is_named(
    services, tmp_path, monkeypatch
):
    root = init_repo(tmp_path / "plans")
    (root / ".dplanner").write_text("gone\n")
    dialog = open_dialog(services, monkeypatch)
    dialog.picker.set_current(root)
    assert dialog.pages.currentWidget() is dialog.empty and "No projects" in dialog.empty.text()
    assert dialog.note.isVisibleTo(dialog) and "gone" in dialog.note.text()
    assert not dialog.add_button.isEnabled()
    dialog.deleteLater()


def test_adding_connects_the_chosen_projects_to_the_library(services, plans, monkeypatch):
    chosen = [plans / "search", plans / "billing"]

    class Fake:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 1

        def chosen(self):
            return chosen

        def deleteLater(self):  # noqa: N802 - Qt's name
            pass

    monkeypatch.setattr(projects_module, "OpenProjectsDialog", Fake)
    run(services, "projects.browse")
    assert [p.title for p in services.document.projects] == ["Search", "Billing"]
    assert (
        services.repo.project_dir(services.document.projects[0].id) == (plans / "search").resolve()
    )
    assert "2 projects added" in services.window.statusBar().currentMessage()
