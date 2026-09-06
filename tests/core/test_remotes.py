"""One name for a remote however it is spelt, and what git says about a directory.

``canonical_remote`` is what discovery matches a code checkout's origin against a project's
recorded repository with; ``remote_label`` is what a person sees; ``activity`` is what the
project browser shows beside each plan a repository holds.
"""

import subprocess
from pathlib import Path

import pytest

from dplanner.core.storage.locations import Activity, activity, canonical_remote, remote_label


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Acme/Widget.git",
        "https://github.com/acme/widget/",
        "git@github.com:acme/widget.git",
        "ssh://git@github.com/acme/widget",
        "ssh://git@GitHub.com:22/acme/widget.git",
        "  https://user:token@github.com/acme/widget  ",
    ],
)
def test_every_spelling_of_a_github_remote_is_one_name(url):
    assert canonical_remote(url) == "github.com/acme/widget"


def test_another_host_keeps_its_name():
    assert canonical_remote("https://gitlab.com/group/sub/repo.git") == "gitlab.com/group/sub/repo"
    assert canonical_remote("host.example:plans.git") == "host.example/plans"


def test_a_local_path_is_its_resolved_self(tmp_path):
    target = tmp_path / "origin.git"
    assert canonical_remote(str(target)) == str(target.resolve())
    assert canonical_remote(f"file://{target}") == str(target.resolve())
    assert canonical_remote("") == ""


def test_a_windows_drive_letter_is_a_path_not_a_host():
    assert canonical_remote(r"C:\code\widget").endswith(r"C:\code\widget")


def test_the_label_keeps_the_owners_spelling():
    assert remote_label("git@github.com:Acme/Widget.git") == "Acme/Widget"
    assert remote_label("https://gitlab.com/Group/Repo.git") == "gitlab.com/Group/Repo"
    assert remote_label("") == ""


def _commit(repo: Path, path: str, author: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(author)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            f"user.name={author}",
            "-c",
            "user.email=who@example.com",
            "commit",
            "-qm",
            path,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "plans"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _commit(repo, "search/project.dproj", "Anna")
    _commit(repo, "billing/project.dproj", "Bo")
    _commit(repo, "search/steps/one/step.json", "Bo")
    return repo


def test_activity_reads_one_directory(repo):
    found = activity(repo, "search")
    assert found.last_author == "Bo"
    assert found.authors == ("Bo", "Anna")
    assert found.commits == 2
    assert found.last_when.startswith("20")


def test_activity_over_the_whole_tree_and_over_nothing(repo, tmp_path):
    assert activity(repo).commits == 3
    assert activity(repo, "nowhere") == Activity("", "", (), 0)
    assert activity(tmp_path / "not-a-repo") == Activity("", "", (), 0)


def test_the_limit_bounds_the_walk(repo):
    assert activity(repo, "", limit=1).commits == 1
