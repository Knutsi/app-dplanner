"""A playbook's ``progress``: the step's PR merged into its feature branch and the step accepted
by the merge — and everything that makes the merge right checked before it, because a merge
cannot be taken back. ``gh`` is faked at the module's door; nothing reaches GitHub."""

from io import StringIO

import pytest

from dplanner.cli import CliContext
from dplanner.cli.discovery import open_library
from dplanner.cli.lookup import find_step
from dplanner.domain.model import Step
from dplanner.modules import default_module_formats
from dplanner.modules.github import cli as github_cli
from dplanner.modules.github.aspect import PR_MERGED, GithubRefs, read
from dplanner.modules.github.gh import GhError, PrInfo

HEAD = "agent/s1-build-it"  # The step's own branch: its worktree's.


def pr(state: str, base: str = "feature/x", head: str = HEAD) -> PrInfo:
    return PrInfo(4, "Build it", state, "u4", head, base)


@pytest.fixture
def gh(monkeypatch):
    """gh as a script: what ``view_pr`` answers in turn, and every merge asked for."""
    answers: list[PrInfo] = []
    merged: list[tuple[str, int]] = []
    monkeypatch.setattr(github_cli, "view_pr", lambda *_: answers.pop(0) if answers else None)
    monkeypatch.setattr(github_cli, "default_branch", lambda _repo: "main")
    monkeypatch.setattr(github_cli, "merge_pr", lambda repo, n: merged.append((repo, n)))
    return answers, merged


@pytest.fixture
def ready(cli, plan):
    """The step under review with PR #4 recorded."""
    cli("github", "set", "Build it", "--pr", "4")
    cli("status", "set", "Build it", "ready-for-review")


def accept(
    cli_library, finished: list[str], base: str = "feature/x"
) -> tuple[tuple[str, bool], GithubRefs | None]:
    """Progress on "Build it", the plan putting its PR's base at ``base``."""

    def finish(_context: CliContext, step: Step) -> bool:
        finished.append(step.id)
        return True

    with open_library(cli_library, default_module_formats(), StringIO()) as context:
        step = find_step(context.library, "Build it", None)
        said = github_cli.accept_by_merge(context, step, base=base, head=HEAD, finish_merged=finish)
        return said, read(context.library.step(step.id))


def test_progress_merges_into_the_feature_branch_and_accepts_the_step(ready, cli_library, gh):
    answers, merged = gh
    answers += [pr("open"), pr("merged")]
    finished: list[str] = []
    said, refs = accept(cli_library, finished)
    assert said == ("", False) and merged == [("acme/widget", 4)] and len(finished) == 1
    assert refs is not None and refs.pr_state == PR_MERGED and refs.pr_base == "feature/x"


def test_a_step_moved_off_its_stretch_is_never_merged_and_goes_to_a_person(ready, cli_library, gh):
    """Its PR still opens against the old feature branch; the plan now says the mainline."""
    answers, merged = gh
    answers.append(pr("open", base="feature/x"))
    said, _refs = accept(cli_library, [], base="")
    assert said == ("the step's work goes to the mainline, which a person merges", True)
    assert merged == [] and answers  # gh was not even asked.


@pytest.mark.parametrize(
    ("answer", "base", "refusal", "mainline"),
    [
        (pr("open", base="main"), "main", "main is acme/widget's default branch", True),
        (
            pr("open", base="feature/y"),
            "feature/x",
            "goes from agent/s1-build-it into feature/y",
            False,
        ),
        (
            pr("open", head="agent/other"),
            "feature/x",
            "goes from agent/other into feature/x",
            False,
        ),
        (pr("closed"), "feature/x", "is closed, not merged", False),
    ],
)
def test_progress_merges_nothing_the_plan_does_not_expect(
    ready, cli_library, gh, answer, base, refusal, mainline
):
    answers, merged = gh
    answers.append(answer)
    finished: list[str] = []
    (why, to_mainline), _refs = accept(cli_library, finished, base=base)
    assert refusal in why and to_mainline is mainline
    assert merged == [] and finished == []


def test_a_step_not_waiting_on_review_is_not_merged(cli, plan, cli_library, gh):
    answers, merged = gh
    cli("github", "set", "Build it", "--pr", "4")
    answers.append(pr("open"))
    (why, to_mainline), _refs = accept(cli_library, [])
    assert "the step is pending" in why and not to_mainline and merged == []


def test_progress_says_why_when_there_is_no_pr_or_gh_refuses(cli, plan, cli_library, monkeypatch):
    cli("status", "set", "Build it", "ready-for-review")
    assert accept(cli_library, [])[0] == ("the step has no pull request recorded", False)
    cli("github", "set", "Build it", "--pr", "4")

    def refused(_repo, _n):
        raise GhError("HTTP 401")

    monkeypatch.setattr(github_cli, "view_pr", refused)
    assert accept(cli_library, [])[0] == ("gh: HTTP 401", False)
