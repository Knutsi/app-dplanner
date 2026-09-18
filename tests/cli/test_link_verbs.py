"""``dplanner project share`` and ``project open`` — the link, from a terminal.

The window's half and this one write and read the same document, so the tests that matter
are the two ends meeting: what ``share`` prints is what ``open`` takes. The verb that
cannot clone is the other subject — ``library add``'s rule applies here too, so an unknown
plan repository is a refusal that names the command to run, not a fetch.
"""

import json
import subprocess

from dplanner.core.storage.locations import init_repo
from dplanner.domain.project_link import SUFFIX, read

ORIGIN = "https://github.com/acme/plans"
CODE = "https://github.com/acme/widget"


def data(text):
    return json.loads(text)


def published(tmp_path, cli, name="plans"):
    """A plan repository with a remote and one project in it, in this library."""
    root = init_repo(tmp_path / name)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", ORIGIN], check=True)
    cli("project", "create", "Search", "--in", str(root), "--code", CODE)
    return root


def clone_of(root, dest):
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e.com",
            "commit",
            "-qm",
            "x",
        ],
        check=True,
    )
    subprocess.run(["git", "clone", "-q", str(root), str(dest)], check=True)
    # The clone's origin is the path it came from; the link's is the published URL, so the
    # clone is re-pointed at what the link actually names.
    subprocess.run(["git", "-C", str(dest), "remote", "set-url", "origin", ORIGIN], check=True)
    return dest


# -- share -----------------------------------------------------------------------------------


def test_share_prints_a_link_carrying_both_repositories(cli, tmp_path):
    published(tmp_path, cli)
    said = cli("project", "share", "Search").strip()
    link = read(said)
    assert link.plan_remote == ORIGIN and link.plan_path == "search"
    assert link.code_remote == CODE and link.title == "Search"


def test_share_json_carries_the_link_and_the_document_it_would_write(cli, tmp_path):
    published(tmp_path, cli)
    row = data(cli("project", "share", "Search", "--json"))
    assert row["link"].startswith("dplanner://project?")
    assert row["document"]["plan"] == {"remote": ORIGIN, "path": "search"}
    assert row["document"]["code"] == {"remote": CODE}


def test_share_writes_a_file_and_gives_it_the_suffix(cli, tmp_path):
    published(tmp_path, cli)
    target = tmp_path / "out" / "search"  # No suffix, and no directory yet.
    row = data(cli("project", "share", "Search", "--file", str(target), "--json"))
    written = target.with_suffix(SUFFIX)
    assert row["file"] == str(written)
    assert read(str(written)).plan_remote == ORIGIN


def test_a_plan_nobody_can_clone_is_refused_with_what_to_do(cli, workspace):
    cli("project", "create", "Discovery")  # The test workspace has no remote.
    said = cli("project", "share", "Discovery", expect=1)
    assert "no remote" in said and "publish it to GitHub" in said


# -- open ------------------------------------------------------------------------------------


def test_open_adds_the_project_out_of_the_clone_the_link_is_pointed_at(cli, tmp_path):
    root = published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    cli("library", "remove", "Search")
    assert "Search" not in cli("library", "list")
    here = clone_of(root, tmp_path / "here")
    said = cli("project", "open", link, "--into", str(here))
    assert "Added 'Search'" in said
    assert data(cli("project", "show", "Search", "--json"))["dir"] == str(here / "search")


def test_open_finds_the_clone_this_library_already_uses_without_being_told(cli, tmp_path):
    root = published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    here = clone_of(root, tmp_path / "here")
    # Another project out of the same clone is what makes that clone known to the library.
    cli("project", "create", "Billing", "--in", str(here))
    cli("library", "remove", "Search")
    assert "Added 'Search'" in cli("project", "open", link)
    assert data(cli("project", "show", "Search", "--json"))["dir"] == str(here / "search")


def test_open_records_the_checkout_it_was_given(cli, tmp_path):
    root = published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    cli("library", "remove", "Search")
    here = clone_of(root, tmp_path / "here")
    code = init_repo(tmp_path / "widget")
    cli("project", "open", link, "--into", str(here), "--checkout", str(code))
    assert data(cli("project", "show", "Search", "--json"))["checkout"] == str(code.resolve())


def test_open_takes_a_file_as_readily_as_a_line(cli, tmp_path):
    root = published(tmp_path, cli)
    path = tmp_path / f"search{SUFFIX}"
    cli("project", "share", "Search", "--file", str(path))
    cli("library", "remove", "Search")
    here = clone_of(root, tmp_path / "here")
    assert "Added 'Search'" in cli("project", "open", str(path), "--into", str(here))


def test_open_never_clones_and_says_what_to_run_instead(cli, tmp_path):
    published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    cli("library", "remove", "Search")
    said = cli("project", "open", link, expect=1)
    assert f"git clone {ORIGIN}" in said and "--into" in said


def test_open_refuses_a_project_already_in_the_library(cli, tmp_path):
    root = published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    here = clone_of(root, tmp_path / "here")
    assert "already in the library" in cli("project", "open", link, "--into", str(here), expect=1)


def test_open_refuses_a_clone_without_the_project_the_link_names(cli, tmp_path):
    root = published(tmp_path, cli)
    link = cli("project", "share", "Search").strip()
    cli("library", "remove", "Search")
    bare = init_repo(tmp_path / "bare")
    said = cli("project", "open", link, "--into", str(bare), expect=1)
    assert "no project at search" in said and "pull it" in said
    assert root.is_dir()


def test_open_refuses_something_that_is_not_a_link(cli, tmp_path):
    assert "not a dplanner" in cli("project", "open", "https://github.com/acme/plans", expect=1)
