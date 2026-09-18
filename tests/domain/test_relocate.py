"""Moving a plan — out of the code it plans, and on from a plan repository picked
wrongly — in the one function both surfaces call."""

import json
import subprocess

import pytest

from dplanner.core.storage.locations import canonical_remote, init_repo
from dplanner.core.storage.pointer import POINTER_FILE, read_index
from dplanner.domain.library_file import read_library_file, write_library_file
from dplanner.domain.model import Step
from dplanner.domain.relocate import RelocateError, move_project
from dplanner.domain.seed import seed_project
from dplanner.domain.store import PROJECT_META, LibraryStore


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _repo(path, origin=""):
    repo = init_repo(path)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    if origin:
        _git(repo, "remote", "add", "origin", origin)
    return repo


def _commit_all(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "plan")


@pytest.fixture
def colocated(tmp_path):
    """A plan kept inside its code repository, committed there, open in a library."""
    code = _repo(tmp_path / "widget", "git@github.com:acme/widget.git")
    (code / "src").mkdir()
    (code / "src" / "main.py").write_text("print()\n")
    directory = seed_project(code / "planning", "Search rewrite")
    (directory / "modules").mkdir()
    (directory / "modules" / "spec.md").write_text("# Topology\n")
    path = tmp_path / "library.json"
    write_library_file(path, [directory])
    store = LibraryStore(path)
    library = store.load()
    project = library.projects[0]
    library.add_child(project.id, Step(title="Read the spec"))
    store.flush({(project.id, "structure")})
    _commit_all(code)
    plans = _repo(tmp_path / "plans")
    return store, library, code, plans


def test_the_plan_moves_with_its_files_index_lines_and_two_commits(colocated):
    store, library, code, plans = colocated
    project = library.projects[0]

    moved = move_project(store, project.id, plans / "search-rewrite")

    target = (plans / "search-rewrite").resolve()
    assert moved.target.resolve() == target and not (code / "planning").exists()
    assert (target / "steps" / "read-the-spec" / "step.json").is_file()
    assert (target / "modules" / "spec.md").read_text() == "# Topology\n"
    meta = json.loads((target / PROJECT_META).read_text())
    # As git names the remote — which a machine may rewrite (an insteadOf rule), so the
    # comparison is the canonical one every reader makes.
    [row] = meta["locations"]
    assert row["role"] == "code" and canonical_remote(row["repository"]) == "github.com/acme/widget"
    assert "colocation" not in meta
    assert read_index(plans) == ["search-rewrite"] and not (code / POINTER_FILE).exists()
    file = read_library_file(store.library_path)
    assert file.projects == [target]
    assert file.checkouts == {"github.com/acme/widget": code.resolve()}
    assert store.project_dir(project.id) == target
    assert store.checkout_for("git@github.com:acme/widget.git") == code.resolve()
    assert canonical_remote(project.locations[0].repository) == "github.com/acme/widget"
    assert moved.source_committed and moved.target_committed and moved.notes == ()
    assert _git(code, "log", "-1", "--format=%s").startswith("Move the plan of «Search rewrite»")
    assert _git(code, "status", "--porcelain") == ""
    assert _git(plans, "log", "-1", "--format=%s").strip() == "Add «Search rewrite»"
    assert (code / "src" / "main.py").is_file()


def test_the_target_must_be_free_and_inside_a_repository(colocated, tmp_path):
    store, library, _code, plans = colocated
    project_id = library.projects[0].id
    (plans / "taken").mkdir()
    with pytest.raises(RelocateError, match="already exists"):
        move_project(store, project_id, plans / "taken")
    with pytest.raises(RelocateError, match="git repository"):
        move_project(store, project_id, tmp_path / "loose" / "search")
    moved = move_project(store, project_id, tmp_path / "fresh" / "search", init_repo=True)
    assert (tmp_path / "fresh" / ".git").is_dir()
    assert (moved.target / PROJECT_META).is_file()


def test_moving_into_the_code_repository_is_refused(colocated):
    store, library, code, _plans = colocated
    with pytest.raises(RelocateError, match="code repository"):
        move_project(store, library.projects[0].id, code / "elsewhere")


def test_a_plan_moves_on_between_plan_repositories_and_keeps_its_code(colocated, tmp_path):
    """The second move is the one that puts a wrong pick right. What it must not do is
    inherit: the repository it leaves this time is a plan repository, not the code's, so
    the code repository and the checkout are the ones already recorded."""
    store, library, code, plans = colocated
    project = library.projects[0]
    move_project(store, project.id, plans / "search-rewrite")
    elsewhere = _repo(tmp_path / "elsewhere")

    moved = move_project(store, project.id, elsewhere / "search-rewrite")

    target = (elsewhere / "search-rewrite").resolve()
    assert moved.target.resolve() == target and not (plans / "search-rewrite").exists()
    assert (target / "steps" / "read-the-spec" / "step.json").is_file()
    assert read_index(elsewhere) == ["search-rewrite"] and read_index(plans) == []
    assert canonical_remote(project.locations[0].repository) == "github.com/acme/widget"
    # Not the plan repository it happened to leave: the checkout it already had.
    assert store.checkout_for("git@github.com:acme/widget.git") == code.resolve()
    file = read_library_file(store.library_path)
    assert file.projects == [target]
    assert file.checkouts == {"github.com/acme/widget": code.resolve()}


def test_a_plan_that_never_had_a_checkout_here_gains_none_by_moving(colocated, tmp_path):
    """A move must not invent a code checkout out of the plan repository it left."""
    store, library, _code, plans = colocated
    project = library.projects[0]
    move_project(store, project.id, plans / "search-rewrite")
    store.set_checkout("git@github.com:acme/widget.git", None)
    elsewhere = _repo(tmp_path / "elsewhere")

    move_project(store, project.id, elsewhere / "search-rewrite")

    assert store.checkout_for("git@github.com:acme/widget.git") is None
    assert read_library_file(store.library_path).checkouts == {}


def test_unsaved_edits_refuse_the_move(colocated):
    store, library, _code, plans = colocated
    project = library.projects[0]
    library.set_field(project.id, "summary", "typing…")
    with pytest.raises(RelocateError, match="unsaved"):
        move_project(store, project.id, plans / "search")
