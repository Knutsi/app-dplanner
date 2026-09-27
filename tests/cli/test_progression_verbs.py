"""``dplanner progression show --all``: the Control Centre's question in the terminal — what
can start anywhere, each row naming its project and whether an agent works it.

No ``qapp`` fixture: the verb is Qt-free by rule.
"""

import json
from datetime import date

import pytest

from dplanner.modules.progression.cli import NO_PROJECT, SEVERAL


@pytest.fixture
def cli(cli):
    """Alpha: finishing *Map the API* (an agent's) frees one, *Write the docs* none. Beta:
    finishing *Order parts* frees two, *Paint* none."""
    cli("project", "create", "Alpha")
    cli("step", "add", "Alpha", "Map the API")
    cli("step", "add", "Alpha", "Write the docs")
    cli("step", "add", "Alpha", "Wire the API", "--after", "map-the-api")
    cli("agent", "on", "map-the-api")
    cli("project", "create", "Beta")
    cli("step", "add", "Beta", "Order parts")
    cli("step", "add", "Beta", "Paint")
    cli("step", "add", "Beta", "Assemble", "--after", "order-parts")
    cli("step", "add", "Beta", "Test the rig", "--after", "order-parts")
    return cli


def test_every_project_is_one_board_ranked_by_what_finishing_frees(cli):
    """Ties go library order: *Write the docs* before *Paint*, both freeing nothing."""
    text = cli("progression", "show", "--all")
    assert "0% done — 0 of 7 steps across 2 projects" in text
    assert (
        "Ready to start:\n"
        "  Beta · Order parts  (unblocks 2)\n"
        "  Alpha · Map the API  (agent, unblocks 1)\n"
        "  Alpha · Write the docs\n"
        "  Beta · Paint\n"
    ) in text
    assert "Up next:\n  Alpha · Wire the API  (after Map the API)" in text


def test_the_json_names_each_row_s_project_and_whether_an_agent_works_it(cli):
    found = json.loads(cli("progression", "show", "--all", "--json"))
    assert [project["title"] for project in found["projects"]] == ["Alpha", "Beta"]
    alpha, beta = (project["id"] for project in found["projects"])
    ready = [(row["title"], row["project"], row["agent"]) for row in found["ready"]]
    assert ready == [
        ("Order parts", beta, False),
        ("Map the API", alpha, True),
        ("Write the docs", alpha, False),
        ("Paint", beta, False),
    ]
    assert found["ready"][0]["unlocks"] == 2
    assert "project" not in found


def test_naming_projects_narrows_the_board_to_them(cli):
    found = json.loads(cli("progression", "show", "--all", "beta", "--json"))
    assert [project["title"] for project in found["projects"]] == ["Beta"]
    assert [row["title"] for row in found["ready"]] == ["Order parts", "Paint"]


def test_one_project_keeps_its_shape_and_its_rows_say_the_rest(cli):
    """The one-project JSON gains fields and loses none: an agent reading it before
    ``--all`` existed reads it still."""
    found = json.loads(cli("progression", "show", "alpha", "--json"))
    assert "projects" not in found
    assert found["project"] == found["ready"][0]["project"]
    assert [(row["title"], row["agent"]) for row in found["ready"]] == [
        ("Map the API", True),
        ("Write the docs", False),
    ]
    text = cli("progression", "show", "alpha")
    assert "Ready to start:\n  Map the API  (agent, unblocks 1)\n  Write the docs" in text


def test_a_board_needs_a_project_or_all_and_one_without_all(cli):
    assert NO_PROJECT in cli("progression", "show", expect=1)
    assert SEVERAL in cli("progression", "show", "alpha", "beta", expect=1)


def test_a_step_behind_a_wait_joins_the_board_on_its_day_and_not_before(cli, clock):
    clock.pin(date(2026, 9, 18))
    cli("step", "add", "Beta", "Parts arrive")
    cli("wait", "set", "parts-arrive", "--until", "2026-09-21")
    cli("step", "add", "Beta", "Unpack", "--after", "parts-arrive")

    def ready():
        found = json.loads(cli("progression", "show", "--all", "--json"))
        return [row["title"] for row in found["ready"]]

    assert "Unpack" not in ready()
    clock.pin(date(2026, 9, 20))
    assert "Unpack" not in ready()
    clock.pin(date(2026, 9, 21))
    assert "Unpack" in ready()
