"""A review's two agents are briefed with the conversation they are about to have.

S1 is an agent's work, carrying a branch and a PR; R2 is its review. ``agent prompt`` on
either side must read as the whole protocol: the review is told whom it reviews, where
that work is, through which lenses, in how many rounds and that it comments rather than
commits; the reviewed step is told not to stop at ready for review but to wait for rounds
and answer them — and either, relaunched mid-review, is handed the round where it stands.

No ``qapp`` fixture: the briefing is assembled Qt-free, exactly as ``agent prompt`` prints it.
"""

import json

import pytest

from dplanner.planning.review import LENSES, NO_WORKTREE_FOR_A_REVIEW


@pytest.fixture
def cli(cli, cli_stdin):
    cli("project", "create", "Widget")
    cli("step", "add", "widget", "Build the parser", "--agent")
    cli_stdin("describe", "set", "S1", "--file", "-", stdin="Parse the widget grammar.")
    cli("step", "add", "widget", "Review the parser", "--after", "S1", "--agent", "--review")
    cli("github", "set", "S1", "--branch", "feat/parser", "--pr", "12")
    return cli


def prompt(cli, step):
    return json.loads(cli("agent", "prompt", step, "--json"))["prompt"]


def section(text, heading):
    """One ``## heading`` block of a briefing, up to the next."""
    assert f"## {heading}\n" in text, f"no {heading!r} in the briefing"
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_a_review_is_briefed_with_its_subject_its_lenses_and_its_cap(cli):
    text = prompt(cli, "R2")

    reviewed = section(text, "Work you review")
    assert "**S1** Build the parser" in reviewed
    assert "branch `feat/parser`" in reviewed and "PR #12" in reviewed

    instructions = section(text, "Instructions")
    for lens in LENSES:
        assert lens.asks in instructions
    assert "at most 3 with S1" in instructions
    assert "`dplanner review post R2 --file <findings.md>`" in instructions
    assert "`dplanner review approve R2`" in instructions
    assert "you never commit" in instructions

    # It reads the subject's work where it is: no worktree of its own to confirm.
    before = section(text, "Before you start")
    assert "own git worktree" not in before
    assert NO_WORKTREE_FOR_A_REVIEW in before

    # Its verdict is its status: no PR of its own, and no status to set by hand.
    done = section(text, "When you are done")
    assert "github set" not in done and "ready-for-review" not in done
    assert "`dplanner review escalate R2" in done


def test_a_lens_this_build_does_not_name_is_passed_on_as_a_skill(cli):
    cli("review", "set", "R2", "--lens", "security", "--lens", "perf")
    instructions = section(prompt(cli, "R2"), "Instructions")
    assert "**perf** — a lens of the developer's own: use your `perf` skill" in instructions
    architecture = next(lens for lens in LENSES if lens.id == "architecture")
    assert architecture.asks not in instructions


def test_a_reviews_description_rides_along_as_what_to_look_for(cli, cli_stdin):
    cli_stdin("describe", "set", "R2", "--file", "-", stdin="Watch the tokenizer's error paths.")
    text = prompt(cli, "R2")
    instructions = section(text, "Instructions")
    assert "What to look for" in instructions
    assert "Watch the tokenizer's error paths." in instructions
    assert "## Description\n" not in text  # Said once, where the review reads it.


def test_a_review_with_nothing_to_review_is_told_to_stop(cli):
    cli("step", "add", "widget", "Lonely review", "--agent", "--review")
    instructions = section(prompt(cli, "R3"), "Instructions")
    assert "reviews nothing yet" in instructions and "Stop" in instructions


def test_the_reviewed_step_is_briefed_to_wait_for_rounds_and_answer_them(cli):
    done = section(prompt(cli, "S1"), "When you are done")
    assert "`dplanner agent-state set S1 pending-approval`" in done
    assert "R2 reviews this step next, in at most 3 rounds" in done
    assert "`dplanner review wait S1`" in done
    assert "`dplanner review reply S1 --file <reply.md>`" in done
    assert "done --because" not in done  # A review is on its way: it decides done.


def test_a_step_under_review_is_briefed_with_the_findings_posted_to_it(cli):
    cli("status", "set", "S1", "ready-for-review")
    cli("review", "start", "R2")
    cli("review", "post", "R2", "--text", "tokenizer.py:40 swallows the error.")

    rounds = section(prompt(cli, "S1"), "Review rounds with R2")
    assert "S1 has R2's findings for round 1" in rounds
    assert "tokenizer.py:40 swallows the error." in rounds
    assert "`dplanner review take S1`" in rounds

    # The review, relaunched, sees the same conversation from its side.
    assert "tokenizer.py:40" in section(prompt(cli, "R2"), "Review rounds with S1")

    # Once it has ended there is nothing left to pick up.
    cli("review", "take", "S1")
    cli("review", "reply", "S1", "--text", "Raised it.")
    cli("review", "approve", "R2")
    assert "## Review rounds" not in prompt(cli, "S1")


def test_a_review_runs_in_no_worktree_and_the_verb_says_why(cli):
    refused = cli("agent", "worktree", "R2", "on", expect=1)
    assert NO_WORKTREE_FOR_A_REVIEW in refused
    cli("agent", "worktree", "S1", "on")  # The work it reviews keeps its own choice.


def test_a_review_is_briefed_by_its_aspect_so_lint_asks_for_no_description(cli):
    cli("step", "add", "widget", "Undescribed work", "--agent")
    found = json.loads(cli("project", "lint", "widget", "--json", expect=1))["findings"]
    missing = {row["title"] for row in found if row["check"] == "agent.missing"}
    assert missing == {"Undescribed work"}  # Not the review, whose aspect briefs it.
