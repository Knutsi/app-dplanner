"""``dplanner checklist show``: the rows, the order, the words and the exit code.

Every check here is a fake probe. Nothing in this file asks the machine anything — which is
the point of the seam: a check is a record with a callable, so the report can be tested
without a subprocess, a network or a keychain.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.checklist import (
    GROUPS,
    MachineCheck,
    Reading,
    Remedy,
    commands,
    ordered,
    summary,
)
from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run


def check(check_id, group="Services", *, ok=True, detail="", required=False, remedy=None):
    return MachineCheck(
        id=check_id,
        group=group,
        label=check_id,
        probe=lambda: Reading(ok=ok, detail=detail),
        remedy=remedy,
        required=required,
    )


@pytest.fixture
def checklist_cli():
    def invoke(checks, *argv, expect=0):
        registry = CliRegistry()
        registry.register_all(commands(checks))
        out, err = StringIO(), StringIO()
        code = run(registry, [], ["checklist", "show", *argv], out, err)
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue()

    return invoke


def test_the_rows_are_grouped_in_the_tables_order_with_the_required_first():
    read = ordered(
        [
            check("advice", "Agents"),
            check("later", "Other tools"),
            check("needed", "Agents", required=True),
            check("first", "DPlanner", required=True),
        ]
    )

    assert [one.id for one in read] == ["first", "needed", "advice", "later"]
    assert [one.group for one in read] == ["DPlanner", "Agents", "Agents", "Other tools"]


def test_a_group_the_table_does_not_name_is_refused():
    with pytest.raises(ValueError, match="Wishes"):
        ordered([check("stray", "Wishes")])


def test_every_group_in_the_table_is_spelled_the_same_way_twice():
    assert len(set(GROUPS)) == len(GROUPS)


def test_a_required_row_that_fails_is_the_exit_code(checklist_cli):
    said = checklist_cli(
        [check("git.installed", "Git and GitHub", ok=False, detail="not on PATH", required=True)],
        expect=1,
    )

    assert "problem" in said
    assert "1 required item needs attention" in said


def test_a_failing_recommendation_is_advice_and_exits_zero(checklist_cli):
    said = checklist_cli([check("github.gh", "Git and GitHub", ok=False, detail="not on PATH")])

    assert "advice" in said and "problem" not in said
    assert "Everything required is in place — 1 suggestion." in said


def test_a_machine_with_everything_says_so(checklist_cli):
    said = checklist_cli([check("git.installed", "Git and GitHub", ok=True, detail="git 2.51.0")])

    assert "This machine has everything." in said
    assert "git 2.51.0" in said


def test_a_failing_rows_remedy_is_printed_with_the_command_to_type(checklist_cli):
    remedy = Remedy(
        words="Install or update DPlanner on this machine.",
        command="dplanner install all",
        action="install.dplanner",
        verb="Install…",
    )
    said = checklist_cli(
        [check("install.skill", "DPlanner", ok=False, required=True, remedy=remedy)], expect=1
    )

    assert "Install or update DPlanner on this machine." in said
    assert "$ dplanner install all" in said


def test_a_row_that_is_well_keeps_its_remedy_to_itself(checklist_cli):
    remedy = Remedy(words="Install or update DPlanner on this machine.")
    said = checklist_cli([check("install.skill", "DPlanner", ok=True, remedy=remedy)])

    assert "Install or update" not in said


def test_json_carries_every_row_with_its_remedy_and_the_two_counts(checklist_cli):
    remedy = Remedy(words="Sign in.", command="gh auth login")
    said = checklist_cli(
        [
            check("git.installed", "Git and GitHub", ok=True, detail="git 2.51.0", required=True),
            check("github.auth", "Git and GitHub", ok=False, remedy=remedy),
        ],
        "--json",
    )
    data = json.loads(said)

    assert data["failing"] == 1
    assert data["required_failing"] == 0
    assert [row["check"] for row in data["checks"]] == ["git.installed", "github.auth"]
    assert data["checks"][0]["remedy"] is None
    assert data["checks"][1]["remedy"] == {
        "words": "Sign in.",
        "command": "gh auth login",
        "action": "",
    }
    assert data["summary"] == summary(
        [(check("github.auth", ok=False), Reading(ok=False))],
    )


def test_the_verb_needs_no_library():
    (command,) = commands([])

    assert command.needs_library is False
    assert command.edits_graph is None  # It reshapes nothing; the topology gate is not its.
