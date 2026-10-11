"""A project whose code is two repositories: every step's PR is read, merged and linked in the
repository the step works in — its workplace — never the primary for all of them.

The case that taught it: two repositories each number their PRs from one, so a PR #3 looked
up in the wrong one is somebody else's, and once read a landing done whose own PR was still
open (docs/research/2026-10-11-parallel-branches). ``gh`` is faked at the module's door.
"""

import json
from io import StringIO

import pytest

from dplanner.cli import CliContext
from dplanner.cli.discovery import open_library
from dplanner.cli.lookup import find_step
from dplanner.domain.locations import Location, Placement
from dplanner.domain.model import Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import LibraryStore
from dplanner.modules import default_module_formats
from dplanner.modules.github import cli as github_cli
from dplanner.modules.github.aspect import read
from dplanner.modules.github.gh import PrInfo
from dplanner.planning.agent import code_remote_of, with_workplace
from dplanner.planning.status import Status
from dplanner.planning.status import stored as status_read

UI = "https://github.com/acme/ui"
HEAD = "agent/s2-build-the-ui"


@pytest.fixture
def two(cli, plan):
    """Widget's code is acme/widget (primary) and acme/ui; "Build the UI" works in the UI."""
    cli("location", "add", "widget", "--role", "code", "--repository", UI, "--label", "UI")
    cli("step", "add", "widget", "Build the UI", "--agent")
    cli("agent", "workplace", "Build the UI", "code:UI")
    return cli


@pytest.fixture
def gh(monkeypatch):
    """gh as two repositories, both with a PR #3: what each holds, and every merge asked for."""
    held: dict[tuple[str, int], PrInfo] = {}
    merged: list[tuple[str, int]] = []
    monkeypatch.setattr(github_cli, "which_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(github_cli, "gh_refusal", lambda **_kw: None)
    monkeypatch.setattr(github_cli, "view_pr", lambda repo, n: held.get((repo, n)))
    monkeypatch.setattr(github_cli, "default_branch", lambda _repo: "main")
    monkeypatch.setattr(github_cli, "merge_pr", lambda repo, n: merged.append((repo, n)))
    return held, merged


def steps_of(cli_library) -> dict[str, Step]:
    library = LibraryStore(cli_library).load()
    return {step.title: step for project in library.projects for step in project.steps}


def test_a_merged_pr_in_one_repository_never_finishes_a_step_of_the_other(two, gh, cli_library):
    held, _merged = gh
    held[("acme/widget", 3)] = PrInfo(3, "Build it", "merged", f"{UI}/pull/3", "a", "main")
    held[("acme/ui", 3)] = PrInfo(3, "Build the UI", "open", f"{UI}/pull/3", "b", "main")
    for title in ("Build it", "Build the UI"):
        two("github", "set", title, "--pr", "3")
        two("status", "set", title, "ready-to-merge")

    report = json.loads(two("github", "refresh", "--json"))

    assert report["finished"] == 1
    steps = steps_of(cli_library)
    assert status_read(steps["Build it"]) is Status.DONE
    assert status_read(steps["Build the UI"]) is Status.READY_TO_MERGE
    refs = read(steps["Build the UI"])
    assert refs is not None and refs.pr_state == "open" and refs.pr_title == "Build the UI"


def test_progress_merges_the_pr_in_the_steps_own_repository(two, gh, cli_library):
    held, merged = gh
    held[("acme/ui", 3)] = PrInfo(3, "Build the UI", "open", "u", HEAD, "feature/x")
    two("github", "set", "Build the UI", "--pr", "3")
    two("status", "set", "Build the UI", "ready-for-review")

    def finish(_context: CliContext, _step: Step) -> bool:
        return True

    with open_library(cli_library, default_module_formats(), StringIO()) as context:
        step = find_step(context.library, "Build the UI", None)
        github_cli.accept_by_merge(context, step, base="feature/x", head=HEAD, finish_merged=finish)

    assert merged == [("acme/ui", 3)]


def test_a_pr_url_from_the_other_repository_is_refused(two, gh):
    said = two("github", "set", "Build the UI", "--pr", "https://github.com/acme/widget/pull/3",
               expect=1)  # fmt: skip
    assert "acme/widget" in said and "acme/ui" in said
    two("github", "set", "Build the UI", "--pr", f"{UI}/pull/3")


def test_a_workplace_names_only_a_code_row():
    """A spec row the workplace names is no place to work: the primary stands in, as for a
    row that is gone — and lint says so."""
    code = Location("l1", "code", "https://github.com/acme/widget")
    spec = Location("l2", "spec", "https://github.com/acme/specs")
    facts = RepositoryFacts(None, "", (Placement(code, None), Placement(spec, None)), "")
    step = Step(title="Write it")
    step.module_data["step_agent_instruction"] = with_workplace(step, "l2")
    assert code_remote_of(facts, step) == code.repository


def test_lint_names_a_workplace_whose_row_is_gone(two):
    two("location", "remove", "widget", "code:UI")
    findings = json.loads(two("project", "lint", "widget", "--json", expect=1))["findings"]
    gone = [found for found in findings if found["check"] == "agent.workplace-gone"]
    assert len(gone) == 1 and "Build the UI" in gone[0]["message"]
