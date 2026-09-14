"""``dplanner agent-work …``: the agent announcing itself, and the run that renews it.

The verbs matter less than the two properties around them — that *any* verb is a sign of
life, and that nothing here ever decides an agent has stopped. Both are tested over the
real board the ``cli`` fixture hands every run.
"""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from dplanner.cli.main import run
from dplanner.domain.at_work import FRESH_MINUTES, quiet_seconds
from dplanner.modules import default_module_formats


def data(text):
    return json.loads(text)


@pytest.fixture
def project(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    return "Discovery"


def backdate(board, minutes, step=""):
    """Age the project's claim, as an agent that has said nothing for a while leaves it."""
    (claim,) = [row for row in board.claims() if row.step == step]
    path = board._path(claim.project, step)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["seen"] = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")


def test_an_agent_says_what_it_is_at_work_on(cli, project, at_work_board):
    out = cli("agent-work", "start", "Cutting the graph", "--of", "12", "--project", project)
    assert "An agent is at work on Discovery — Cutting the graph · 0 of 12" in out
    (claim,) = at_work_board.claims()
    assert (claim.doing, claim.of, claim.step) == ("Cutting the graph", 12, "")


def test_progress_moves_along_and_keeps_what_it_was_not_given(cli, project, at_work_board):
    cli("agent-work", "start", "Cutting the graph", "--of", "12", "--project", project)
    out = cli("agent-work", "set", "--done", "8", "--project", project)
    assert "Cutting the graph · 8 of 12" in out


def test_set_alone_is_enough_to_say_an_agent_is_at_work(cli, project, at_work_board):
    cli("agent-work", "set", "Linking the steps", "--project", project)
    assert [claim.doing for claim in at_work_board.claims()] == ["Linking the steps"]


def test_a_claim_names_the_step_it_is_on(cli, project, at_work_board):
    out = cli("agent-work", "start", "Building the modal", "--step", "S1", "--project", project)
    assert "on Discovery · S1 — Building the modal" in out
    (claim,) = at_work_board.claims()
    assert claim.step


def test_several_agents_on_one_plan_are_several_claims(cli, project, at_work_board):
    cli("step", "add", "Discovery", "Draft the model")
    cli("agent-work", "start", "Shaping", "--project", project)
    cli("agent-work", "start", "Building", "--step", "S1", "--project", project)
    cli("agent-work", "start", "Drafting", "--step", "S2", "--project", project)
    assert len(at_work_board.claims()) == 3
    rows = data(cli("agent-work", "show", "--json", "--project", project))
    assert {row["doing"] for row in rows} == {"Shaping", "Building", "Drafting"}


def test_ending_takes_the_claim_away(cli, project, at_work_board):
    cli("agent-work", "start", "Cutting the graph", "--project", project)
    assert "no agent at work" in cli("agent-work", "end", "--project", project)
    assert at_work_board.claims() == []
    assert "nothing was claimed" in cli("agent-work", "end", "--project", project)


def test_ending_one_step_leaves_the_plan_claim(cli, project, at_work_board):
    cli("agent-work", "start", "Shaping", "--project", project)
    cli("agent-work", "start", "Building", "--step", "S1", "--project", project)
    cli("agent-work", "end", "--step", "S1", "--project", project)
    assert [claim.doing for claim in at_work_board.claims()] == ["Shaping"]


def test_show_says_nothing_when_nobody_is_working(cli, project):
    assert "no agent at work" in cli("agent-work", "show", "--project", project)


# -- the sign of life ---------------------------------------------------------------------------


def test_any_verb_renews_the_claim(cli, project, at_work_board):
    """An agent that is working is already running verbs; it should not have to remember a
    heartbeat on top of them."""
    cli("agent-work", "start", "Cutting the graph", "--project", project)
    backdate(at_work_board, 30)
    assert quiet_seconds(at_work_board.claims()[0]) > 60
    cli("status", "set", "S1", "done", "--project", project)
    assert quiet_seconds(at_work_board.claims()[0]) < 60


def test_running_a_verb_never_makes_a_claim(cli, project, at_work_board):
    cli("status", "set", "S1", "done", "--project", project)
    assert at_work_board.claims() == []


def test_a_run_that_is_nobody_s_sign_of_life_renews_nothing(
    registry, cli, cli_library, project, at_work_board
):
    """The developer's own terminal. ``entry.py`` hands the run a board only from inside an
    agent's shell, because renewing a claim says "that agent is still there" and only the
    agent can say it."""
    cli("agent-work", "start", "Cutting the graph", "--project", project)
    backdate(at_work_board, 30)
    code = run(
        registry,
        default_module_formats(),
        ["--library", str(cli_library), "--project", project, "status", "set", "S1", "done"],
        StringIO(),
        StringIO(),
    )
    assert code == 0
    assert quiet_seconds(at_work_board.claims()[0]) > 60


def test_a_quiet_claim_keeps_its_place(registry, cli, cli_library, project, at_work_board):
    """Nothing here can see a process, so nothing here decides one has died: the record says
    how long it has been silent and waits to be ended. Read from the developer's side, whose
    own run is nobody's sign of life and so does not renew what it is about to print."""
    cli("agent-work", "start", "Cutting the graph", "--project", project)
    backdate(at_work_board, FRESH_MINUTES + 10)
    out = StringIO()
    run(
        registry,
        default_module_formats(),
        ["--library", str(cli_library), "--project", project, "agent-work", "show", "--json"],
        out,
        StringIO(),
    )
    (row,) = data(out.getvalue())
    assert row["at_work"] is False and "last heard" in row["heard"]
    assert len(at_work_board.claims()) == 1
