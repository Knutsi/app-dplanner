"""``dplanner agent coordinate``: the coordinator's briefing over a selection, refused for a
squad word already running, a selection across projects or with no agent step, or a word that
is not one — and, with no word given, the briefing that leaves it to the coordinator."""

import json

import pytest

from dplanner.domain import claims


@pytest.fixture
def project(cli, workspace, monkeypatch):
    cli("project", "create", "Discovery")
    monkeypatch.setenv("DPLANNER_PROJECT", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("step", "add", "Discovery", "Cut the graph", "--after", "Read the spec")
    cli("agent", "on", "S1")
    cli("agent", "on", "S2")
    return workspace / "discovery"


def test_the_briefing_names_the_claim_the_roster_and_what_is_ready(cli, project):
    said = json.loads(
        cli("agent", "coordinate", "S2", "S1", "--callsign", "Kettle", "--at-once", "2", "--json")
    )
    assert said["callsign"] == "kettle-actual"
    assert [(s["key"], s["callsign"]) for s in said["steps"]] == [
        ("S2", "kettle-two"),
        ("S1", "kettle-three"),
    ]
    prompt = said["prompt"]
    assert "`dplanner claim take S2 S1 --callsign kettle`" in prompt
    assert "**S1** Read the spec — pending · ready" in prompt
    assert "**S2** Cut the graph — pending · waits on S1" in prompt
    assert "at most 2 runs live at once" in prompt
    assert "start nothing while a window reads 90 %" in prompt
    assert "Never stand in for a review gate or a person gate" in prompt
    assert sum(segment["chars"] for segment in said["segments"]) == said["chars"]


def test_a_squad_word_already_running_is_refused_and_the_taken_words_named(cli, project):
    cli("claim", "take", "S1", "--callsign", "kettle")
    said = cli("agent", "coordinate", "S2", "--callsign", "kettle", expect=1)
    (claim,) = claims.records(project)
    assert f"squad kettle is running already ({claim.short})" in said
    assert "taken: kettle" in said
    assert "Coordinate" in cli("agent", "coordinate", "S2", "--callsign", "anvil")


def test_a_selection_spans_one_project_and_a_squad_word_is_one_word(cli, project):
    cli("project", "create", "Billing")
    invoice = json.loads(cli("step", "add", "Billing", "Invoice", "--json"))["id"]
    assert "one project at a time" in cli(
        "agent", "coordinate", "S1", invoice, "--callsign", "anvil", expect=1
    )
    assert "one lowercase word" in cli(
        "agent", "coordinate", "S1", "--callsign", "anvil-two", expect=1
    )


def test_with_no_word_the_coordinator_chooses_its_own_and_is_told_the_words_in_use(cli, project):
    cli("claim", "take", "S1", "--callsign", "kettle")
    said = json.loads(cli("agent", "coordinate", "S2", "--json"))
    assert said["callsign"] == ""
    assert [s["callsign"] for s in said["steps"]] == [""]
    prompt = said["prompt"]
    assert prompt.index("## Choose your squad word") < prompt.index("## Before you start")
    assert "Running now: kettle." in prompt
    assert "`dplanner claim take S2 --callsign <word>` with your word" in prompt
    assert "If it refuses the word, another squad holds it: pick another" in prompt
    assert "- **<word> Two** (`<word>-two`) — works S2" in prompt
    assert "`DPLANNER_CALLSIGN=<word>-actual`" in prompt


def test_a_step_nobody_s_agent_works_is_context_without_a_member(cli, project):
    cli("step", "add", "Discovery", "Sign off", "--after", "Cut the graph")
    said = json.loads(cli("agent", "coordinate", "S3", "S2", "--callsign", "anvil", "--json"))
    assert [(s["key"], s["callsign"]) for s in said["steps"]] == [
        ("S3", ""),
        ("S2", "anvil-two"),
    ]
    prompt = said["prompt"]
    assert "**S3** Sign off — pending · a person's step, which waits on a person" in prompt
    assert "context only, no member" in prompt
    assert "`dplanner claim take S2 --callsign anvil`" in prompt
    assert "anvil-three" not in prompt
    assert "holds none" in cli("agent", "coordinate", "S3", expect=1)
