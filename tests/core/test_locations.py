"""Parsing a workspace reference, and picking the provider that fits what is there."""

import subprocess

import pytest

from dplanner.core.storage.git import GitStorage
from dplanner.core.storage.github import GitHubStorage
from dplanner.core.storage.local import LocalStorage
from dplanner.core.storage.locations import open_storage, parse_location
from dplanner.core.storage.provider import StorageError


def test_a_bare_path_has_no_scheme():
    assert parse_location("~/Plans/roadmap").scheme == ""


@pytest.mark.parametrize("scheme", ["file", "git", "github"])
def test_known_schemes_are_recognised(scheme):
    location = parse_location(f"{scheme}:target")
    assert (location.scheme, location.target) == (scheme, "target")


def test_an_unknown_prefix_is_treated_as_a_path():
    """Only the schemes we define are schemes; everything else is somebody's folder name."""
    assert parse_location("C:/Users/knut").scheme == ""


def test_an_empty_reference_is_refused():
    with pytest.raises(StorageError):
        parse_location("   ")


def test_a_plain_folder_opens_as_local(tmp_path):
    assert isinstance(open_storage(str(tmp_path / "ws")), LocalStorage)


def test_a_git_checkout_opens_as_git(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", tmp_path], check=True)
    storage = open_storage(str(tmp_path / "ws"))
    assert isinstance(storage, GitStorage)
    assert not isinstance(storage, GitHubStorage)


def test_a_checkout_with_a_remote_opens_as_github(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", tmp_path], check=True)
    subprocess.run(
        ["git", "-C", tmp_path, "remote", "add", "origin", "https://github.com/o/r.git"],
        check=True,
    )
    assert isinstance(open_storage(str(tmp_path / "ws")), GitHubStorage)


def test_an_explicit_scheme_overrides_the_detection(tmp_path):
    """`file:` on a git checkout is a supported way to say "no version control today"."""
    subprocess.run(["git", "init", "-q", "-b", "main", tmp_path], check=True)
    storage = open_storage(f"file:{tmp_path / 'ws'}")
    assert isinstance(storage, LocalStorage)
    assert not isinstance(storage, GitStorage)


def test_git_scheme_on_a_plain_folder_is_refused(tmp_path):
    with pytest.raises(StorageError, match="not inside a git repository"):
        open_storage(f"git:{tmp_path / 'ws'}")


def test_a_github_location_needs_somewhere_to_clone_into():
    with pytest.raises(StorageError, match="clone into"):
        open_storage("github:owner/repo")
