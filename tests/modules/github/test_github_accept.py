"""A playbook's ``progress``: the step's PR merged into its feature branch and the step accepted
by the merge — never into the repository's default branch, which a person merges. ``gh`` is
faked at the module's door; nothing reaches GitHub."""

from io import StringIO

import pytest

from dplanner.cli.discovery import open_library
from dplanner.cli.lookup import find_step
from dplanner.modules import default_module_formats
from dplanner.modules.github import cli as github_cli
from dplanner.modules.github.aspect import PR_MERGED, read
from dplanner.modules.github.gh import GhError, PrInfo


def pr(state: str, base: str = "feature/x") -> PrInfo:
    return PrInfo(4, "Build it", state, "u4", "agent/s1-build-it", base)


@pytest.fixture
def gh(monkeypatch):
    """gh as a script: what ``view_pr`` answers in turn, and every merge asked for."""
    answers: list[PrInfo] = []
    merged: list[tuple[str, int]] = []
    monkeypatch.setattr(github_cli, "view_pr", lambda _repo, _n: answers.pop(0) if answers else None)
    monkeypatch.setattr(github_cli, "default_branch", lambda _repo: "main")
    monkeypatch.setattr(github_cli, "merge_pr", lambda repo, n: merged.append((repo, n)))
    return answers, merged


def accept(cli_library, finished: list[str]) -> tuple[str, object]:
    with open_library(cli_library, default_module_formats(), StringIO()) as context:
        step = find_step(context.library, "Build it", None)
        said = github_cli.accept_by_merge(
            context,
            step,
            finish_merged=lambda _context, done: finished.append(done.id) is None,
        )
        return said, read(context.library.step(step.id))


def test_progress_merges_into_the_feature_branch_and_accepts_the_step(cli, plan, cli_library, gh):
    answers, merged = gh
    cli("github", "set", "Build it", "--pr", "4")
    answers += [pr("open"), pr("merged")]
    finished: list[str] = []
    said, refs = accept(cli_library, finished)
    assert said == "" and merged == [("acme/widget", 4)] and len(finished) == 1
    assert refs is not None and refs.pr_state == PR_MERGED and refs.pr_base == "feature/x"


@pytest.mark.parametrize(
    ("answer", "refusal"),
    [
        (pr("open", base="main"), "goes into the default branch"),
        (pr("closed"), "is closed, not merged"),
    ],
)
def test_progress_never_merges_into_the_default_branch_nor_a_closed_pr(
    cli, plan, cli_library, gh, answer, refusal
):
    answers, merged = gh
    cli("github", "set", "Build it", "--pr", "4")
    answers.append(answer)
    finished: list[str] = []
    said, _refs = accept(cli_library, finished)
    assert refusal in said and merged == [] and finished == []


def test_progress_says_why_when_there_is_no_pr_or_gh_refuses(cli, plan, cli_library, monkeypatch):
    assert accept(cli_library, [])[0] == "the step has no pull request recorded"
    cli("github", "set", "Build it", "--pr", "4")

    def refused(_repo, _n):
        raise GhError("HTTP 401")

    monkeypatch.setattr(github_cli, "view_pr", refused)
    assert accept(cli_library, [])[0] == "gh: HTTP 401"
