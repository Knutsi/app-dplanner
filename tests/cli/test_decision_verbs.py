"""``dplanner decision``: the log beside a project, safe to write twice, and what an
agent's briefing carries of it. No ``qapp`` fixture: this is an agent's workflow."""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.decisions.log import read_log


def data(text):
    return json.loads(text)


@pytest.fixture
def project(cli, cli_stdin):
    cli("project", "create", "Search rewrite")
    cli("step", "add", "Search rewrite", "Draft the model", "--agent")
    cli_stdin("describe", "set", "S1", "--file", "-", stdin="Draft it.")
    return "Search rewrite"


def log(cli_library):
    return read_log(LibraryStore(cli_library).load().projects[0])


# -- recording ----------------------------------------------------------------------------------


def test_add_mints_ids_stamps_the_day_and_names_the_step_by_key(cli, project, cli_library):
    said = cli(
        "decision",
        "add",
        project,
        "Keep the index in SQLite",
        "--step",
        "S1",
        "--text",
        "Postgres would need an operator.",
        "--made",
        "2026-09-05",
    )
    assert "D1: Keep the index in SQLite — recorded" in said
    (record,) = log(cli_library)
    assert record.id == "D1" and record.made == "2026-09-05"
    assert record.body == "Postgres would need an operator."
    assert record.step  # the step's id, not its key
    listed = data(cli("decision", "list", project, "--json"))["decisions"]
    assert listed[0]["key"] == "S1" and listed[0]["decision"] == "D1"
    assert "D1   Keep the index in SQLite  5 September  on S1" in cli("decision", "list", project)


def test_a_title_already_in_the_log_is_that_decision_not_a_second(cli, project, cli_library):
    """A retry after a stale-workspace refusal, or an epilogue run twice, must not leave
    two records; the answer names the existing one and how to revise it."""
    cli("decision", "add", project, "Keep the index in SQLite", "--text", "first")
    said = cli("decision", "add", project, "keep the index in sqlite ", "--text", "second")
    assert "D1: already recorded" in said and "decision set" in said
    (record,) = log(cli_library)
    assert record.body == "first"
    assert (
        data(cli("decision", "add", project, "Keep the index in SQLite", "--json"))["outcome"]
        == "unchanged"
    )


def test_add_stamps_today_when_nobody_says_and_refuses_a_bad_day(cli, project, cli_library):
    from datetime import date

    cli("decision", "add", project, "Ship weekly")
    assert log(cli_library)[0].made == date.today().isoformat()
    assert "YYYY-MM-DD" in cli("decision", "add", project, "Later", "--made", "soon", expect=1)


def test_a_reversal_supersedes_the_earlier_decision(cli, project, cli_library):
    cli("decision", "add", project, "Keep the index in SQLite")
    cli("decision", "add", project, "Move the index to Postgres", "--supersedes", "d1")
    _first, second = log(cli_library)
    assert second.supersedes == "D1"
    listed = cli("decision", "list", project)
    assert "D2" in listed and "D1" not in listed.split("(1 superseded")[0]
    assert "1 superseded — `--all`" in listed
    everything = cli("decision", "list", project, "--all")
    assert "D1   Keep the index in SQLite" in everything and "superseded by D2" in everything
    assert "no decision 'D9'" in cli(
        "decision", "add", project, "Again", "--supersedes", "D9", expect=1
    )


def test_set_revises_the_fields_and_remove_survives_a_second_run(
    cli, cli_stdin, project, cli_library
):
    cli("decision", "add", project, "Keep the index in SQLite", "--step", "S1")
    cli_stdin(
        "decision",
        "set",
        project,
        "D1",
        "--title",
        "Keep SQLite",
        "--file",
        "-",
        "--no-step",
        "--made",
        "2026-09-01",
        stdin="Read-mostly, one operator.",
    )
    (record,) = log(cli_library)
    assert (record.title, record.body, record.step, record.made) == (
        "Keep SQLite",
        "Read-mostly, one operator.",
        "",
        "2026-09-01",
    )
    shown = cli("decision", "show", project, "sqlite")
    assert "D1   Keep SQLite" in shown and "Read-mostly, one operator." in shown
    assert "D1: Keep SQLite — removed" in cli("decision", "remove", project, "D1")
    assert log(cli_library) == []
    assert "nothing to remove" in cli("decision", "remove", project, "D1")


def test_removing_a_superseded_decision_unlinks_its_successor(cli, project, cli_library):
    cli("decision", "add", project, "One")
    cli("decision", "add", project, "Two", "--supersedes", "D1")
    cli("decision", "remove", project, "D1")
    (record,) = log(cli_library)
    assert record.id == "D2" and record.supersedes == ""


def test_an_ambiguous_name_is_refused_with_the_ids(cli, project):
    cli("decision", "add", project, "Index in SQLite")
    cli("decision", "add", project, "Index in memory")
    said = cli("decision", "show", project, "Index", expect=1)
    assert "several decisions" in said and "D1" in said and "D2" in said
    assert "decision list" in cli("decision", "show", project, "ghost", expect=1)
    assert "cannot supersede itself" in cli(
        "decision", "set", project, "D1", "--supersedes", "D1", expect=1
    )


def test_the_log_is_one_file_beside_the_project_with_absence_for_the_defaults(
    cli, project, workspace
):
    cli("decision", "add", project, "Ship weekly", "--made", "2026-09-05")
    entry = json.loads(next(workspace.glob("*/modules/decisions.json")).read_text())
    assert entry == {
        "format": 1,
        "decisions": [{"id": "D1", "title": "Ship weekly", "made": "2026-09-05"}],
    }
    cli("decision", "remove", project, "D1")
    assert not list(workspace.glob("*/modules/decisions.json"))


# -- what an agent is told ----------------------------------------------------------------------


def test_the_briefing_carries_the_standing_decisions_and_not_the_superseded(cli, project):
    cli(
        "decision",
        "add",
        project,
        "Keep the index in SQLite",
        "--text",
        "One operator.",
        "--made",
        "2026-09-05",
        "--step",
        "S1",
    )
    cli("decision", "add", project, "Ship weekly", "--made", "2026-09-06")
    cli("decision", "add", project, "Ship daily", "--supersedes", "D2", "--made", "2026-09-07")
    prompt = data(cli("agent", "prompt", "S1", "--json"))["prompt"]
    assert "## Decisions so far" in prompt
    assert "- **D1 Keep the index in SQLite** (2026-09-05, on S1)\n  One operator." in prompt
    assert "- **D3 Ship daily** (2026-09-07)" in prompt
    assert "Ship weekly" not in prompt
    assert "dplanner decision add" in prompt


def test_a_project_with_no_decisions_briefs_none(cli, project):
    prompt = data(cli("agent", "prompt", "S1", "--json"))["prompt"]
    assert "Decisions so far" not in prompt
