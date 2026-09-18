"""The kept clone door: a full working clone under the configuration directory, made
hardened and left ordinary."""

import pytest
from tests.modules.spec_git_helpers import clean_git, git, make_remote  # noqa: F401

from dplanner.core.storage.kept import CHECKOUTS_DIR, clone_full, is_kept, kept_dir


def test_a_kept_clone_has_one_directory_per_repository_whatever_the_spelling(tmp_path):
    https = kept_dir(tmp_path, "https://github.com/Acme/Widget.git")
    ssh = kept_dir(tmp_path, "git@github.com:acme/widget")
    assert https == ssh and https.parent == tmp_path / CHECKOUTS_DIR
    assert https.name.startswith("widget-") and len(https.name) == len("widget-") + 16
    assert kept_dir(tmp_path, "https://github.com/acme/ui") != https
    assert is_kept(https, tmp_path) and not is_kept(tmp_path / "Code" / "widget", tmp_path)


def test_a_full_clone_lands_whole_and_ordinary(tmp_path, clean_git):  # noqa: F811
    remote = make_remote(tmp_path / "remote", {"README.md": "# Widget\n", "src/app.py": "x = 1\n"})
    dest = kept_dir(tmp_path / "config", remote.url)
    clone_full(remote.url, dest)
    assert (dest / ".git").is_dir() and (dest / "src" / "app.py").read_text() == "x = 1\n"
    assert not dest.with_name(f"{dest.name}.partial").exists()
    # Every blob, no sparse pattern, and the clone-time hardening left nothing behind:
    # an agent working here finds git as it is everywhere else.
    assert git("config", "--get", "remote.origin.url", cwd=dest).strip() == remote.url
    listed = git("config", "--list", "--local", cwd=dest)
    for key in ("core.hookspath", "protocol.allow", "core.symlinks", "gc.auto", "blob:none"):
        assert key not in listed.lower()


def test_the_door_refuses_what_the_cache_door_refuses(tmp_path):
    with pytest.raises(ValueError):
        clone_full("-oProxyCommand=evil", tmp_path / "x")
    with pytest.raises(ValueError):
        clone_full("https://user:secret@github.com/acme/widget", tmp_path / "x")
