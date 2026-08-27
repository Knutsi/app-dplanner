"""The GitHub aspect through the CLI: recording gh-less, enriching with gh, refreshing.

No ``qapp`` fixture — ``aspect.py``, ``cli.py`` and ``gh.py`` are Qt-free by rule. Every
gh call is monkeypatched: these tests must pass with no ``gh`` installed and no network.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.domain.store import ProductStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.github import cli as github_cli
from dplanner.modules.github.aspect import GithubRefs, read, summary, write
from dplanner.modules.github.gh import PrInfo

MERGED = PrInfo(number=12, title="Add login flow", state="merged", url="u12", head_ref="feat/login")
OPEN = PrInfo(number=7, title="Fix crash", state="open", url="u7", head_ref="fix/crash")


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    return root


@pytest.fixture
def cli(workspace):
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(
            registry, default_module_formats(), ["--workspace", str(workspace), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery")
    invoke("step", "add", "Discovery", "Read the spec")
    return invoke


@pytest.fixture
def gh_less(monkeypatch):
    monkeypatch.setattr(github_cli, "which_gh", lambda: None)
    monkeypatch.setattr(github_cli, "gh_refusal", lambda **_kw: "gh not found on PATH")


@pytest.fixture
def gh_present(monkeypatch):
    monkeypatch.setattr(github_cli, "which_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(github_cli, "gh_refusal", lambda **_kw: None)


def reload(workspace):
    return ProductStore(LocalStorage(workspace)).load()


def first_step(product):
    return product.projects[0].steps[0]


def stored_refs(workspace) -> GithubRefs:
    refs = read(first_step(reload(workspace)))
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


def test_summary_says_the_pr_and_its_terminal_state(cli, workspace, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    assert summary(first_step(reload(workspace))) == "feat/login"
    cli("github", "set", "Read the spec", "--pr", "12")
    assert summary(first_step(reload(workspace))) == "PR #12"


# -- recording, with and without gh ------------------------------------------------------------


def test_a_branch_is_recorded_without_gh(cli, workspace, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    refs = read(first_step(reload(workspace)))
    assert refs == GithubRefs(branch="feat/login")


def test_a_pr_set_without_gh_still_records_the_number(cli, workspace, gh_less):
    cli("github", "set", "Read the spec", "--pr", "#12")
    refs = stored_refs(workspace)
    assert refs.pr_number == 12 and refs.pr_state == ""


def test_a_pr_set_with_gh_fills_state_title_url_and_branch(cli, workspace, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: MERGED)
    cli("product", "set", "--repository", "https://github.com/acme/widget")
    cli("github", "set", "Read the spec", "--pr", "12")
    assert stored_refs(workspace) == GithubRefs(
        branch="feat/login",
        pr_number=12,
        pr_url="u12",
        pr_state="merged",
        pr_title="Add login flow",
    )


def test_setting_one_half_keeps_the_other(cli, workspace, gh_less):
    cli("github", "set", "Read the spec", "--branch", "feat/login")
    cli("github", "set", "Read the spec", "--pr", "12")
    refs = stored_refs(workspace)
    assert refs.branch == "feat/login" and refs.pr_number == 12


def test_setting_nothing_is_refused(cli, gh_less):
    assert "nothing to set" in cli("github", "set", "Read the spec", expect=1)


def test_a_ref_that_names_no_pr_is_refused(cli, gh_less):
    assert "names no PR" in cli("github", "set", "Read the spec", "--pr", "soon", expect=1)


def test_clearing_halves_and_the_whole(cli, workspace, gh_less):
    modules = workspace / "projects/discovery/steps/read-the-spec/modules"
    cli("github", "set", "Read the spec", "--branch", "feat/login", "--pr", "12")
    cli("github", "clear", "Read the spec", "--pr")
    assert read(first_step(reload(workspace))) == GithubRefs(branch="feat/login")
    cli("github", "clear", "Read the spec")
    assert not (modules / "github.json").exists()
    assert "no GitHub refs" in cli("github", "clear", "Read the spec", expect=1)


# -- the gh-gated verbs ------------------------------------------------------------------------


def test_gh_gated_verbs_refuse_without_gh(cli, gh_less):
    assert "gh not found" in cli("github", "prs", expect=1)
    assert "gh not found" in cli("github", "branches", expect=1)
    assert "gh not found" in cli("github", "refresh", expect=1)


def test_gh_gated_verbs_refuse_without_a_repository(cli, gh_present):
    assert "product set --repository" in cli("github", "prs", expect=1)


def test_prs_lists_open_by_default_and_all_on_request(cli, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "list_prs", lambda repo: [MERGED, OPEN])
    cli("product", "set", "--repository", "https://github.com/acme/widget")
    assert json.loads(cli("github", "prs", "--json"))["prs"] == [
        {"number": 7, "state": "open", "title": "Fix crash", "branch": "fix/crash"}
    ]
    assert len(json.loads(cli("github", "prs", "--all", "--json"))["prs"]) == 2


def test_branches_come_from_gh(cli, gh_present, monkeypatch):
    monkeypatch.setattr(github_cli, "list_branches", lambda repo: ["main", "feat/login"])
    cli("product", "set", "--repository", "https://github.com/acme/widget")
    assert json.loads(cli("github", "branches", "--json"))["branches"] == ["main", "feat/login"]


def test_refresh_rechecks_only_open_and_unknown_prs(cli, workspace, gh_present, monkeypatch):
    cli("product", "set", "--repository", "https://github.com/acme/widget")
    cli("step", "add", "Discovery", "Write the docs")
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: None)
    cli("github", "set", "Read the spec", "--pr", "12")  # Recorded with state "".
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: MERGED)

    report = json.loads(cli("github", "refresh", "--json"))
    assert report == {"checked": 1, "updated": 1}
    assert stored_refs(workspace).pr_state == "merged"

    # Now merged: a second refresh has nothing left to check.
    assert json.loads(cli("github", "refresh", "--json")) == {"checked": 0, "updated": 0}


def test_refresh_without_changes_reports_zero_updates(cli, gh_present, monkeypatch):
    cli("product", "set", "--repository", "https://github.com/acme/widget")
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, number: OPEN)
    cli("github", "set", "Read the spec", "--pr", "7")
    assert json.loads(cli("github", "refresh", "--json")) == {"checked": 1, "updated": 0}
