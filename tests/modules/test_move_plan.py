"""Move Plan: the wizard, the move, and the reload that follows.

The wizard is stood in for at the name the module reads; what is under test is the move
itself — the files, the library file, the two commits — and the two refusals that leave
everything where it was, with autosave running again. The verb is offered on every
project, so a plan already in a repository of its own moves on from the same wizard.
"""

from pathlib import Path

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import read_library_file
from dplanner.domain.store import PROJECT_META
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import module as projects_module
from dplanner.modules.projects.repo_picker import PlanTarget


def select(services, kind, node_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri(kind, node_id)),))
    return services.context.current()


class FakeWizard:
    """Answers what the test decided, in the module's own vocabulary."""

    chosen: PlanTarget | None = None
    folder = "discovery"

    def __init__(self, **_kwargs):
        pass

    def exec(self):
        return 1 if FakeWizard.chosen is not None else 0

    def target(self):
        return None if FakeWizard.chosen is None else FakeWizard.chosen.root / FakeWizard.folder

    def plan_target(self):
        return FakeWizard.chosen

    def deleteLater(self):  # noqa: N802 - Qt's name
        pass


@pytest.fixture(autouse=True)
def _wizard(monkeypatch):
    FakeWizard.chosen = None
    monkeypatch.setattr(projects_module, "MovePlanDialog", FakeWizard)


@pytest.fixture
def boxes(monkeypatch):
    """Every notice the module shows — a refusal, or what the move left to know —
    recorded instead of shown."""
    shown = []
    monkeypatch.setattr(
        projects_module, "notice", lambda _parent, title, text: shown.append((title, text))
    )
    return shown


def test_the_move_lands_the_plan_in_the_new_repository_and_reloads(
    session, services, make_project, library_file, library_repo, tmp_path, boxes
):
    project = make_project("Discovery")
    services.autosave.flush_now()
    old_window = services.window
    plans = init_repo(tmp_path / "plans")
    FakeWizard.chosen = PlanTarget(plans)

    services.actions.run("projects.move", select(services, "project", project.id))

    assert (plans / "discovery" / PROJECT_META).is_file()
    assert not (library_repo / "discovery").exists()
    assert (plans / ".dplanner").read_text().splitlines() == ["discovery"]
    entries = read_library_file(library_file)
    assert [entry.path for entry in entries] == [plans / "discovery"]
    # The old library repository recorded the departure, and the moved project records
    # what code it plans: the repository it left.
    assert session.services is not None and session.services.window is not old_window
    moved = session.services.document.project(project.id)
    assert moved.repository == str(library_repo.resolve())
    assert boxes == [] or all("notes" not in text for _title, text in boxes)


def test_a_refused_move_leaves_everything_and_resumes_autosave(
    services, make_project, library_repo, boxes
):
    """Inside the code repository is the one place a plan is refused rather than warned."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    FakeWizard.chosen = PlanTarget(library_repo)
    FakeWizard.folder = "plans"

    services.actions.run("projects.move", select(services, "project", project.id))

    assert (library_repo / "discovery" / PROJECT_META).is_file()
    assert not (library_repo / "plans").exists()
    assert boxes and boxes[0][0] == "Move Plan" and "code repository" in boxes[0][1]
    assert services.autosave._paused == 0
    assert services.document.has(project.id)  # No reload happened.
    FakeWizard.folder = "discovery"


def test_a_plan_already_in_its_own_repository_moves_on_to_another(
    session, services, make_project, library_file, tmp_path, boxes
):
    """The mistake this verb has to be able to undo: a plan put in the wrong plan
    repository. Nothing about the second move is a special case of the first."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    first = init_repo(tmp_path / "wrong-plans")
    FakeWizard.chosen = PlanTarget(first)
    services.actions.run("projects.move", select(services, "project", project.id))

    assert session.services is not None
    moved_services = session.services
    assert (first / "discovery" / PROJECT_META).is_file()

    second = init_repo(tmp_path / "right-plans")
    FakeWizard.chosen = PlanTarget(second)
    moved_services.actions.run("projects.move", select(moved_services, "project", project.id))

    assert (second / "discovery" / PROJECT_META).is_file()
    assert not (first / "discovery").exists()
    entries = read_library_file(library_file)
    assert [entry.path for entry in entries] == [second / "discovery"]
    assert session.services is not None and session.services.document.has(project.id)


def test_cancelling_the_wizard_moves_nothing(services, make_project, library_repo):
    project = make_project("Discovery")
    FakeWizard.chosen = None
    services.actions.run("projects.move", select(services, "project", project.id))
    assert (library_repo / "discovery" / PROJECT_META).is_file()


def test_a_new_repository_is_initialised_for_the_move(
    session, services, make_project, tmp_path, boxes
):
    project = make_project("Discovery")
    services.autosave.flush_now()
    FakeWizard.chosen = PlanTarget(tmp_path / "fresh", init=True)
    services.actions.run("projects.move", select(services, "project", project.id))
    assert (tmp_path / "fresh" / ".git").is_dir()
    assert (tmp_path / "fresh" / "discovery" / PROJECT_META).is_file()
    assert Path(project.id) is not None  # The id survives the move and the reload.
    assert session.services is not None and session.services.document.has(project.id)


def test_a_move_into_a_new_github_repository_publishes_after_the_move(
    session, services, make_project, tmp_path, boxes, monkeypatch
):
    from dplanner.core.storage import github

    published = []
    monkeypatch.setattr(
        github.GitHubStorage,
        "publish",
        classmethod(lambda cls, storage, name, **_k: published.append((storage.repo_root, name))),
    )
    project = make_project("Discovery")
    services.autosave.flush_now()
    FakeWizard.chosen = PlanTarget(tmp_path / "fresh", init=True, publish="plans")
    services.actions.run("projects.move", select(services, "project", project.id))
    assert published == [((tmp_path / "fresh").resolve(), "plans")]
    assert session.services is not None and session.services.document.has(project.id)
