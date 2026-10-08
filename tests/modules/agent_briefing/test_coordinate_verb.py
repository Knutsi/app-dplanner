"""``dplanner agent coordinate``: the coordinator's briefing over a selection, refused for a
squad word already running, a selection across projects, or a word that is not one."""

import json

import pytest

from dplanner.domain import claims


@pytest.fixture
def project(cli, workspace, monkeypatch):
    cli("project", "create", "Discovery")
    monkeypatch.setenv("DPLANNER_PROJECT", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("step", "add", "Discovery", "Cut the graph", "--after", "Read the spec")
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
