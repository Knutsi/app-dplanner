"""The GitHub aspect through the CLI: recording gh-less, enriching with gh, refreshing.

No ``qapp`` fixture — ``aspect.py``, ``cli.py`` and ``gh.py`` are Qt-free by rule. Every
gh call is monkeypatched: these tests must pass with no ``gh`` installed and no network.

Which repository a step's refs belong to is the **code repository its project records**;
a project that records none — the older shape, a plan kept beside its code — falls back to
its own directory's ``origin`` remote, so most tests here add a real remote with git and
one sets the repository through the CLI.
"""

import json
import subprocess

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.github import cli as github_cli
from dplanner.modules.github.aspect import GithubRefs, read, summary, write
from dplanner.modules.github.gh import PrInfo

MERGED = PrInfo(number=12, title="Add login flow", state="merged", url="u12", head_ref="feat/login")
OPEN = PrInfo(number=7, title="Fix crash", state="open", url="u7", head_ref="fix/crash")


def add_origin(repo, url):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    return cli


@pytest.fixture
def origin(cli, workspace):
    """The workspace repository, pointed at GitHub — what the gh-backed verbs derive from."""
    add_origin(workspace, "https://github.com/acme/widget.git")


@pytest.fixture
def gh_less(monkeypatch):
    monkeypatch.setattr(github_cli, "which_gh", lambda: None)
    monkeypatch.setattr(github_cli, "gh_refusal", lambda **_kw: "gh not found on PATH")


@pytest.fixture
def gh_present(monkeypatch):
    monkeypatch.setattr(github_cli, "which_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(github_cli, "gh_refusal", lambda **_kw: None)


@pytest.fixture
def reload(cli_library):
    return lambda: LibraryStore(cli_library).load()


def first_step(library):
    return library.projects[0].steps[0]


def stored_refs(reload) -> GithubRefs:
    refs = read(first_step(reload()))
    assert refs is not None
    return refs


# -- the aspect itself -------------------------------------------------------------------------


def test_refs_round_trip_and_empty_refs_leave_no_entry():
    refs = GithubRefs(branch="feat/login", pr_number=12, pr_url="u", pr_state="open", pr_title="t")
    entry = write(refs)
    assert entry["pr_number"] == 12 and entry["branch"] == "feat/login"
    assert write(GithubRefs()) == {}
    assert write(None) == {}


def test_the_pr_number_is_stored_as_an_int():
    """An identity, not a quantity: a JSON int round-trips byte-stably, unlike the float
    rule's coerced quantities — see the comment on ``write``."""
    assert write(GithubRefs(pr_number=12))["pr_number"] == 12
    assert isinstance(write(GithubRefs(pr_number=12))["pr_number"], int)


def test_summary_says_the_pr_and_its_terminal_state(cli, reload, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    assert summary(first_step(reload())) == "feat/login"
    cli("github", "set", "Read the spec", "--pr", "12")
    assert summary(first_step(reload())) == "PR #12"


# -- recording, with and without gh ------------------------------------------------------------


def test_a_branch_is_recorded_without_gh(cli, reload, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    refs = read(first_step(reload()))
    assert refs == GithubRefs(branch="feat/login")


def test_a_pr_set_without_gh_still_records_the_number(cli, reload, gh_less):
    cli("github", "set", "Read the spec", "--pr", "#12")
    refs = stored_refs(reload)
    assert refs.pr_number == 12 and refs.pr_state == ""


def test_a_pr_set_with_gh_fills_state_title_url_and_branch(
    cli, origin, reload, gh_present, monkeypatch
):
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: MERGED)
    cli("github", "set", "Read the spec", "--pr", "12")
    assert stored_refs(reload) == GithubRefs(
        branch="feat/login",
        pr_number=12,
        pr_url="u12",
        pr_state="merged",
        pr_title="Add login flow",
    )


def test_setting_one_half_keeps_the_other(cli, reload, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    cli("github", "set", "Read the spec", "--pr", "12")
    refs = stored_refs(reload)
    assert refs.branch == "feat/login" and refs.pr_number == 12


def test_setting_nothing_is_refused(cli, gh_less):
    assert "nothing to set" in cli("github", "set", "Read the spec", expect=1)


def test_a_ref_that_names_no_pr_is_refused(cli, gh_less):
    assert "names no PR" in cli("github", "set", "Read the spec", "--pr", "soon", expect=1)


def test_clearing_halves_and_the_whole(cli, workspace, reload, gh_less):
    modules = workspace / "discovery/steps/read-the-spec/modules"
    cli("github", "set", "Read the spec", "--branch", "feat/login", "--pr", "12")
    cli("github", "clear", "Read the spec", "--pr")
    assert read(first_step(reload())) == GithubRefs(branch="feat/login")
    cli("github", "clear", "Read the spec")
    assert not (modules / "github.json").exists()
    # Already clear is success — state-clearing verbs must survive batches.
    assert "no GitHub refs" in cli("github", "clear", "Read the spec")


# -- the gh-gated verbs ------------------------------------------------------------------------


def test_gh_gated_verbs_refuse_without_gh(cli, gh_less):
    assert "gh not found" in cli("github", "prs", "--project", "Discovery", expect=1)
    assert "gh not found" in cli("github", "branches", "--project", "Discovery", expect=1)
    assert "gh not found" in cli("github", "refresh", expect=1)


def test_gh_gated_verbs_refuse_without_a_github_remote(cli, gh_present):
    """No origin on the project's repository: the refusal says how to add one."""
    assert "git remote add origin" in cli("github", "prs", "--project", "Discovery", expect=1)


def test_prs_lists_open_by_default_and_all_on_request(cli, origin, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "list_prs", lambda repo: [MERGED, OPEN])
    assert json.loads(cli("github", "prs", "--project", "Discovery", "--json"))["prs"] == [
        {"number": 7, "state": "open", "title": "Fix crash", "branch": "fix/crash"}
    ]
    shown = cli("github", "prs", "--all", "--project", "Discovery", "--json")
    assert len(json.loads(shown)["prs"]) == 2


def test_branches_come_from_gh(cli, origin, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "list_branches", lambda repo: ["main", "feat/login"])
    shown = cli("github", "branches", "--project", "Discovery", "--json")
    assert json.loads(shown)["branches"] == ["main", "feat/login"]


def test_refresh_rechecks_only_open_and_unknown_prs(cli, origin, reload, gh_present, monkeypatch):
    cli("step", "add", "Discovery", "Write the docs")
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: None)
    cli("github", "set", "Read the spec", "--pr", "12")  # Recorded with state "".
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: MERGED)

    report = json.loads(cli("github", "refresh", "--json"))
    assert report == {"checked": 1, "updated": 1}
    assert stored_refs(reload).pr_state == "merged"

    # Now merged: a second refresh has nothing left to check.
    assert json.loads(cli("github", "refresh", "--json")) == {"checked": 0, "updated": 0}


def test_each_projects_own_repository_answers_for_its_steps(
    cli, tmp_path, workspace, gh_present, monkeypatch
):
    """Two projects, two repositories: a step's refs are asked of its own project's origin."""
    from dplanner.core.storage.locations import init_repo

    add_origin(workspace, "https://github.com/acme/widget.git")
    satellite = init_repo(tmp_path / "second")
    add_origin(satellite, "https://github.com/acme/satellite.git")
    cli("project", "create", "Satellite", "--dir", str(satellite / "satellite"))
    cli("step", "add", "Satellite", "Wire the antenna")

    asked = []

    def view_pr(repo, _number):
        asked.append(repo)
        return OPEN

    monkeypatch.setattr(github_cli, "view_pr", view_pr)
    cli("github", "set", "Wire the antenna", "--pr", "7")
    assert asked == ["acme/satellite"]


def test_the_projects_code_repository_answers_over_the_directorys_origin(
    cli, origin, gh_present, monkeypatch
):
    """A separated plan: the repository recorded on the project, not the plan's own."""
    asked = []

    def list_prs(repo):
        asked.append(repo)
        return []

    monkeypatch.setattr(github_cli, "list_prs", list_prs)
    cli("project", "set", "Discovery", "--repository", "https://github.com/acme/other")
    cli("github", "prs", "--project", "Discovery")
    assert asked == ["acme/other"]


def test_prs_can_ask_a_named_projects_repository(cli, tmp_path, gh_present, monkeypatch):
    from dplanner.core.storage.locations import init_repo

    satellite = init_repo(tmp_path / "second")
    add_origin(satellite, "https://github.com/acme/satellite.git")
    cli("project", "create", "Satellite", "--dir", str(satellite / "satellite"))

    asked = []

    def list_prs(repo):
        asked.append(repo)
        return []

    monkeypatch.setattr(github_cli, "list_prs", list_prs)
    cli("github", "prs", "--project", "Satellite")
    assert asked == ["acme/satellite"]


def test_refresh_without_changes_reports_zero_updates(cli, origin, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: OPEN)
    cli("github", "set", "Read the spec", "--pr", "7")
    assert json.loads(cli("github", "refresh", "--json")) == {"checked": 1, "updated": 0}
