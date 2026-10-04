"""``dplanner review …`` — a review step and its conversation, from two terminals.

S1 is an agent's work, carrying a branch and a PR; R2 is its review, an agent step that
waits on it. The tests walk the conversation the way the two agents do — one verb per
turn, each in its own run — and read back what the plan says after each.

No ``qapp`` fixture: the aspect and its verbs are Qt-free by rule.
"""

import json

import pytest

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.domain.store import LibraryStore
from dplanner.modules.step_review import cli as review_cli
from dplanner.modules.step_review.aspect import (
    ASKER,
    ENDED,
    PARTY,
    last,
    opened,
    rounds,
    said,
    turn,
)
from dplanner.planning.review import (
    MODULE_ID,
    ReviewSettings,
    is_review,
    settings,
    write,
)


def data(text):
    return json.loads(text)


@pytest.fixture
def cli(cli):
    cli("project", "create", "Widget")
    cli("step", "add", "widget", "Build the parser", "--agent")
    cli("step", "add", "widget", "Review the parser", "--after", "S1", "--agent", "--review")
    cli("github", "set", "S1", "--branch", "feat/parser", "--pr", "12")
    return cli


def status(cli, step):
    return data(cli("status", "show", step, "--json"))["status"]


def full_round(cli, number):
    cli("review", "start", "R2")
    cli("review", "post", "R2", "--text", f"finding {number}")
    cli("review", "take", "S1")
    cli("review", "reply", "S1", "--text", f"fixed {number}")


# -- the aspect -------------------------------------------------------------------------------


def test_absence_is_the_default_and_only_a_choice_is_written():
    step = Step(title="Review")
    assert not is_review(step) and settings(step) == ReviewSettings()
    step.module_data[MODULE_ID] = write(ReviewSettings())
    assert step.module_data[MODULE_ID] == {"on": True, "format": 1}
    chosen = ReviewSettings(agent="codex", lenses=("architecture", "perf"), max_rounds=2)
    step.module_data[MODULE_ID] = write(chosen)
    assert is_review(step) and settings(step) == chosen
    step.module_data[MODULE_ID] = {"on": True, "max_rounds": 0, "lenses": "security"}
    assert settings(step) == ReviewSettings()  # What it cannot read is the default.


def test_a_rounds_state_and_turn_are_read_off_its_stamps():
    """Nothing about a round is stored but what was said and when."""
    step = Step(title="Review")

    def now():
        return last(step, "w")

    assert turn(now()) == ASKER  # Nothing asked yet: the reviewer's move.
    for stamps, state, whose in (
        ({}, "open", ASKER),
        ({"findings": "f", "posted": "t2"}, "posted", PARTY),
        ({"taken": "t3"}, "taken", PARTY),
        ({"reply": "r", "replied": "t4"}, "replied", ASKER),
        ({"approved": "t5"}, "approved", ENDED),
    ):
        step.module_data["review_rounds"] = (
            said(step, "w", **stamps) if stamps else opened(step, "w", "t1")
        )
        held = now()
        assert held is not None and held.state == state and turn(held) == whose
    assert [each.number for each in rounds(step)] == [1]


# -- the conversation -------------------------------------------------------------------------


def test_a_review_runs_its_rounds_and_approves(cli):
    """T110: start, post, take, reply, approve — and where each leaves the two steps."""
    cli("status", "set", "S1", "ready-for-review")
    cli("review", "start", "R2")
    assert "findings" in cli("review", "post", "R2", "--text", "Trailing whitespace is lost.")
    assert status(cli, "S1") == "in-progress"
    taken = cli("review", "take", "S1")
    assert "Trailing whitespace is lost." in taken
    cli("review", "reply", "S1", "--text", "Trimmed on read.")
    assert status(cli, "S1") == "ready-for-review"

    said = cli("review", "approve", "R2")
    assert "carrying S1's branch and PR" in said
    assert status(cli, "S1") == "done" and status(cli, "R2") == "ready-to-merge"
    refs = data(cli("github", "show", "R2", "--json"))
    assert refs["branch"] == "feat/parser" and refs["pr_number"] == 12

    shown = data(cli("review", "show", "R2", "--json"))
    (talk,) = shown["conversations"]
    assert talk["turn"] == ENDED and [each["state"] for each in talk["rounds"]] == ["approved"]
    assert talk["rounds"][0]["findings"] == "Trailing whitespace is lost."
    assert talk["rounds"][0]["reply"] == "Trimmed on read."


def test_a_link_into_a_review_frees_it_from_review_on(cli):
    """The review is ready once its subject is ready for review, with no flag set."""
    progression = data(cli("progression", "show", "widget", "--json"))
    assert [row["title"] for row in progression["ready"]] == ["Build the parser"]
    cli("status", "set", "S1", "ready-for-review")
    progression = data(cli("progression", "show", "widget", "--json"))
    assert [row["title"] for row in progression["ready"]] == ["Review the parser"]
    assert "(auto-progress)" in cli("step", "show", "R2")


def test_the_round_cap_hands_the_review_to_a_person(cli):
    """T111: past the cap, start refuses and names both ways out; escalate takes one."""
    cli("review", "set", "R2", "--max-rounds", "2")
    full_round(cli, 1)
    full_round(cli, 2)
    refused = cli("review", "start", "R2", expect=1)
    assert "review approve R2" in refused and "review escalate R2" in refused

    said = cli("review", "escalate", "R2", "--text", "They disagree on the schema.")
    assert status(cli, "R2") == "blocked"
    note_id = said.split(" — ")[1].split()[0]
    note = cli("note", "show", "widget", note_id)
    assert "handoff" in note and "needs a person after 2 rounds" in note
    assert "They disagree on the schema." in note
    assert "handed round 2 to a person" in cli("review", "wait", "S1", "--timeout", "0")


def test_a_round_is_answered_before_the_next_is_opened(cli):
    cli("review", "start", "R2")
    assert "writing its findings" in cli("review", "start", "R2", expect=1)
    cli("review", "post", "R2", "--text", "one thing")
    assert "wait for its answer" in cli("review", "post", "R2", "--text", "again", expect=1)
    assert "approve once it answers" in cli("review", "approve", "R2", expect=1)
    cli("review", "take", "S1", "--from", "R2")
    assert "already taken" in cli("review", "take", "S1")  # Taking twice is no harm.


def test_the_subject_reaching_review_makes_the_review_due(cli):
    said = cli("status", "set", "S1", "ready-for-review")
    assert "Now due: R2 Review the parser — a DPlanner window" in said


def test_findings_posted_to_a_subject_whose_agent_has_gone_make_it_due(cli):
    cli("status", "set", "S1", "ready-for-review")
    cli("review", "start", "R2")
    said = cli("review", "post", "R2", "--text", "The parser drops the last line.")
    assert "Now due: S1 Build the parser — a DPlanner window" in said
    # With its agent still there, nothing is due: it takes the findings itself.
    cli("agent-state", "set", "S1", "pending-approval")
    assert "due" not in cli("progression", "show", "widget")


def test_an_agent_waiting_on_a_person_is_listed_as_waiting_for_you(cli):
    cli("status", "set", "S1", "in-progress")
    cli("agent-state", "set", "S1", "plan-for-review")
    text = cli("progression", "show", "widget")
    assert "Waits for you:\n  Build the parser  (agent)" in text
    assert "Running:" not in text
    found = data(cli("progression", "show", "widget", "--json"))
    assert [row["title"] for row in found["asking"]] == ["Build the parser"]
    assert found["counts"]["asking"] == 1 and found["counts"]["running"] == 0


def test_post_refuses_with_no_round_open_and_names_start(cli):
    assert "review start R2" in cli("review", "post", "R2", "--text", "x", expect=1)
    assert "nothing to answer" in cli("review", "reply", "S1", "--text", "x", expect=1)


def test_set_and_show_say_the_settings(cli):
    said = cli(
        "review", "set", "R2", "--agent", "codex", "--lens", "architecture", "--lens", "perf"
    )
    assert "Codex" in said and "architecture, perf" in said
    shown = data(cli("review", "show", "R2", "--json"))
    assert shown["review"] == {
        "agent": "codex",
        "lenses": ["architecture", "perf"],
        "max_rounds": 3,
    }
    cli("review", "set", "R2", "--agent", "default", "--lens", "none")
    assert data(cli("review", "show", "R2", "--json"))["review"]["lenses"] == []
    with pytest.raises(SystemExit):  # argparse's refusal: the choices are this build's.
        cli("review", "set", "R2", "--agent", "gpt")


def test_clear_shelves_the_review(cli):
    assert "no longer a review" in cli("review", "clear", "R2")
    assert "already no review" in cli("review", "clear", "R2")
    assert data(cli("review", "show", "R2", "--json"))["review"] is None


# -- review wait ------------------------------------------------------------------------------


def test_wait_returns_at_once_when_the_turn_is_already_here(cli):
    cli("status", "set", "S1", "ready-for-review")
    assert cli("review", "wait", "R2", "--timeout", "0").startswith("S1 is ready for review")
    cli("review", "start", "R2")
    cli("review", "post", "R2", "--text", "Trailing whitespace is lost.")
    arrived = cli("review", "wait", "S1", "--timeout", "0")
    assert "Round 1 from R2" in arrived and "Trailing whitespace is lost." in arrived


def test_wait_exits_3_and_says_where_things_stand_when_nothing_arrives(cli):
    said = cli("review", "wait", "S1", "--timeout", "0", expect=review_cli.TIMED_OUT)
    assert "R2 has not opened a round with S1" in said
    assert "dplanner review wait S1" in said


def test_wait_reads_the_plan_again_until_the_round_lands(cli, cli_library):
    """The other side writes between polls, in a run of its own; the waiting side sees it
    because it reads the plan from disk each time, holding nothing open between."""
    polls = []

    def load():
        store = LibraryStore(cli_library)
        try:
            return store.load()
        finally:
            store.close()

    def the_reviewer_writes(_seconds):
        polls.append(_seconds)
        if len(polls) == 1:
            cli("review", "start", "R2")
        elif len(polls) == 2:
            cli("review", "post", "R2", "--text", "Found one.")

    def its_turn(library):
        subject = next(
            step for project in library.projects for step in project.steps if step.number == 1
        )
        review = next(
            step for project in library.projects for step in project.steps if step.number == 2
        )
        return turn(last(review, subject.id)) == PARTY

    library, arrived = review_cli.await_turn(
        load, its_turn, timeout=60, sleep=the_reviewer_writes, clock=lambda: 0.0
    )
    assert arrived and len(polls) == 2
    review = next(step for step in library.projects[0].steps if step.number == 2)
    assert rounds(review)[0].findings == "Found one."


def test_await_turn_gives_up_after_its_timeout():
    ticks = iter([0.0, 1.0, 2.5, 3.5])
    slept: list[float] = []
    _library, arrived = review_cli.await_turn(
        lambda: None,  # type: ignore[arg-type, return-value]
        lambda _library: False,
        timeout=3,
        sleep=slept.append,
        clock=lambda: next(ticks),
        interval=2.0,
    )
    assert not arrived and slept == [2.0, 0.5]


# -- sending work back upstream ---------------------------------------------------------------


def test_a_collector_talks_to_each_source_by_name(cli):
    cli("step", "add", "widget", "A1", "--agent")
    cli("step", "add", "widget", "A2", "--agent")
    cli(
        "step",
        "add",
        "widget",
        "Collect",
        "--after",
        "S3",
        "--after",
        "S4",
        "--agent",
        "--auto-progress",
    )
    assert "name one with --to" in cli("review", "start", "S5", expect=1)
    cli("review", "start", "S5", "--to", "S3")
    cli("review", "post", "S5", "--to", "S3", "--text", "Rebase on main, please.")
    assert status(cli, "S3") == "in-progress"
    assert "Rebase on main, please." in cli("review", "take", "S3")
    cli("review", "reply", "S3", "--text", "Rebased.")
    assert status(cli, "S3") == "ready-for-review"
    refused = cli("review", "approve", "S5", "--to", "S3", expect=1)
    assert "not a review" in refused and "status set" in refused


def test_a_step_that_takes_nobodys_work_has_nobody_to_talk_to(cli):
    assert "takes no step's work" in cli("review", "start", "S1", expect=1)


# -- lint -------------------------------------------------------------------------------------


def findings(cli, check):
    found = data(cli("project", "lint", "widget", "--json", expect=1))["findings"]
    return [row for row in found if row["check"] == check]


def test_lint_names_a_review_with_no_subject_and_one_with_several(cli):
    cli("step", "add", "widget", "Lonely review", "--agent", "--review")
    (lonely,) = findings(cli, "review.subject")
    assert lonely["title"] == "Lonely review" and "step link" in lonely["message"]
    cli("step", "link", "R3", "S1")
    cli("step", "link", "R3", "R2")
    (crowded,) = findings(cli, "review.subject")
    assert "at once" in crowded["message"]


def test_lint_names_a_review_no_agent_will_pick_up(cli):
    cli("agent", "off", "R2")
    (found,) = findings(cli, "review.agent")
    assert "agent on R2" in found["message"]


def test_lint_names_a_step_that_goes_round_the_review(cli):
    cli("step", "add", "widget", "Ship it", "--after", "S1")
    (found,) = findings(cli, "review.bypassed")
    assert found["title"] == "Ship it"
    assert "step unlink S3 S1" in found["message"] and "step link S3 R2" in found["message"]


def test_lint_names_an_agent_this_build_does_not_know(cli, cli_library):
    """Written by a newer build, or by hand: the verb itself offers only what it knows."""
    store = LibraryStore(cli_library)
    library = store.load()
    marks = set()
    store.dirty.connect(lambda owner, aspect: marks.add((owner, aspect)))
    review = next(step for step in library.projects[0].steps if step.number == 2)
    entry = {"on": True, "agent": "gpt-7", "format": 1}
    SetModuleDataCommand(review.id, MODULE_ID, entry).redo(library)
    store.flush(marks)
    store.close()
    (found,) = findings(cli, "review.unknown-agent")
    assert "'gpt-7'" in found["message"] and "--agent default|" in found["message"]
