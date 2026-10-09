"""The ``.dplanner`` index: one line per project a plan repository holds."""

import subprocess

import pytest

from dplanner.core.storage.pointer import (
    POINTER_FILE,
    add_to_index,
    indexed,
    read_index,
    remove_from_index,
    resolve_index,
)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "plans"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_a_project_is_listed_once_by_its_relative_posix_path(repo):
    search = repo / "search"
    search.mkdir()
    assert add_to_index(search) == repo / POINTER_FILE
    assert (repo / POINTER_FILE).read_text() == "search\n"
    assert add_to_index(search) is None
    assert (repo / POINTER_FILE).read_text() == "search\n"
    nested = repo / "teams" / "billing"
    nested.mkdir(parents=True)
    add_to_index(nested)
    assert read_index(repo) == ["search", "teams/billing"]


def test_a_hand_written_line_is_kept_company_not_replaced(repo):
    (repo / POINTER_FILE).write_text("notes/plan\n")
    (repo / "search").mkdir()
    add_to_index(repo / "search")
    assert read_index(repo) == ["notes/plan", "search"]


def test_the_root_itself_and_a_folder_outside_git_write_nothing(repo, tmp_path):
    assert add_to_index(repo) is None
    assert not (repo / POINTER_FILE).exists()
    loose = tmp_path / "loose"
    loose.mkdir()
    assert add_to_index(loose) is None


def test_a_bare_git_directory_above_a_loose_folder_is_no_repository(tmp_path):
    """An old build's sync lock planted ``/tmp/.git`` holding only the lock; the walk took it
    for a repository and wrote the index for every loose project under it at ``/tmp``."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "dplanner-sync.lock").touch()
    loose = tmp_path / "loose"
    loose.mkdir()
    assert add_to_index(loose) is None
    assert not (tmp_path / POINTER_FILE).exists()


def test_resolve_follows_relative_and_absolute_lines(repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (repo / POINTER_FILE).write_text(f"search\n\n{elsewhere}\n")
    assert resolve_index(repo) == [
        ("search", (repo / "search").resolve()),
        (str(elsewhere), elsewhere.resolve()),
    ]


def test_removing_drops_the_line_and_the_file_when_it_empties(repo):
    for name in ("search", "billing"):
        (repo / name).mkdir()
        add_to_index(repo / name)
    remove_from_index(repo / "search")
    assert read_index(repo) == ["billing"]
    remove_from_index(repo / "search")  # Already gone: nothing to do.
    assert read_index(repo) == ["billing"]
    remove_from_index(repo / "billing")
    assert not (repo / POINTER_FILE).exists()


def test_indexed_answers_for_a_listed_project_and_anything_inside_it(repo):
    search = repo / "search"
    search.mkdir()
    assert not indexed(search, repo)
    add_to_index(search)
    assert indexed(search, repo) and indexed(search / "modules" / "github", repo)
    assert not indexed(repo, repo) and not indexed(repo / "billing", repo)
    (repo / POINTER_FILE).write_text(".\nsearch\n")  # A line naming the root lists nothing.
    assert not indexed(repo / "billing", repo)
