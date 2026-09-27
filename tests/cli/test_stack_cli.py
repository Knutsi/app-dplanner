"""``dplanner stack …`` end to end, over a real library: an agent builds and reshapes a stack
from the terminal, cannot link into its middle, and a member removed closes the chain. No
``qapp`` fixture."""

import json

import pytest


@pytest.fixture
def line(cli):
    """Kick-off → One → Two → Three → Wrap-up, as S1 to S5, and a loose Spare as S6."""
    cli("project", "create", "Stacks")
    for title in ("Kick-off", "One", "Two", "Three", "Wrap-up", "Spare"):
        cli("step", "add", "Stacks", title)
    for waiter, on in (("One", "Kick-off"), ("Two", "One"), ("Three", "Two"), ("Wrap-up", "Three")):
        cli("step", "link", waiter, on)
    return cli


def listed(cli):
    return cli("stack", "list", "Stacks").strip().split("  ", 1)[1]


def waits_on(cli, step):
    """The keys of what ``step`` waits on."""
    shown = json.loads(cli("step", "show", step, "--json"))
    return [json.loads(cli("step", "show", i, "--json"))["key"] for i in shown["requires"]]


def test_an_agent_builds_and_reshapes_a_stack_from_the_terminal(line):
    assert "Stacked 3 steps" in line("stack", "make", "S4", "S2", "S3")
    assert listed(line) == "S2 S3 S4"

    assert "Added S7 'Four'" in line("stack", "add", "S2", "--new", "Four")
    assert listed(line) == "S2 S3 S4 S7"
    assert waits_on(line, "S5") == ["S7"]  # The old last's dependent follows the new last.

    line("step", "link", "S6", "S1")
    said = line("stack", "add", "S2", "S6", "--at", "1")
    assert "arrived with no links (1 taken off)" in said
    assert listed(line) == "S6 S2 S3 S4 S7"
    assert waits_on(line, "S6") == ["S1"]  # In front, it takes over the stack's inputs.

    line("stack", "move", "S7", "--to", "2")
    assert listed(line) == "S6 S7 S2 S3 S4"
    assert waits_on(line, "S5") == ["S4"]

    assert "it has no links now" in line("stack", "take-out", "S2")
    assert listed(line) == "S6 S7 S3 S4"
    assert waits_on(line, "S3") == ["S7"] and waits_on(line, "S2") == []

    assert "Dissolved the stack S6 S7 S3 S4" in line("stack", "dissolve", "S3")
    assert line("stack", "list", "Stacks").strip() == "no stacks"


def test_every_stack_verb_answers_in_json(line):
    made = json.loads(line("stack", "make", "S2", "S3", "--json"))
    assert [row["key"] for row in made["stack"]["steps"]] == ["S2", "S3"]
    assert made["stack"]["broken"] is None
    new = json.loads(line("stack", "new", "Stacks", "Alone", "--json"))
    assert [row["title"] for row in new["stack"]["steps"]] == ["Alone"]
    added = json.loads(line("stack", "add", "S2", "S6", "--json"))
    assert added["added"]["key"] == "S6" and added["unlinked"] == 0
    moved = json.loads(line("stack", "move", "S6", "--to", "1", "--json"))
    assert [row["key"] for row in moved["stack"]["steps"]] == ["S6", "S2", "S3"]
    out = json.loads(line("stack", "take-out", "S6", "--json"))
    assert out["taken_out"]["key"] == "S6"
    assert [row["key"] for row in out["stack"]["steps"]] == ["S2", "S3"]
    gone = json.loads(line("stack", "dissolve", "S2", "--json"))
    assert [row["key"] for row in gone["steps"]] == ["S2", "S3"]


def test_a_link_into_a_stacks_middle_is_refused_with_the_way_round_it(line):
    line("stack", "make", "S2", "S3", "S4")
    said = line("step", "link", "S3", "S6", expect=1)
    assert "'Two' is inside a stack: a link into it arrives at its first step, 'One'" in said
    said = line("step", "link", "S6", "S3", expect=1)
    assert "a link out of it leaves from its last step, 'Three'" in said
    line("step", "link", "S2", "S6")  # Into the first: the stack's own input.
    line("step", "link", "S6", "S4", expect=1)  # A cycle, refused before the rule.


def test_removing_a_middle_step_leaves_the_chain_closed(line):
    line("stack", "make", "S2", "S3", "S4")
    line("step", "remove", "S3")
    assert listed(line) == "S2 S4"
    assert waits_on(line, "S4") == ["S2"]


def test_make_refuses_steps_that_are_not_one_line(line):
    said = line("stack", "make", "S2", "S4", expect=1)
    assert "these steps are not one line: 'Three' does not wait on 'One'" in said


def test_lint_names_a_stack_somebody_broke_and_the_link_that_mends_it(line):
    line("stack", "make", "S2", "S3", "S4")
    line("step", "unlink", "S3", "S2")
    said = line("project", "lint", "Stacks", expect=1)
    assert (
        "heads a stack that is no longer one line: S3 does not wait on S2 — "
        "`dplanner step link S3 S2`, or `dplanner stack dissolve S2`"
    ) in said
    assert "not one line" in line("stack", "add", "S2", "S6", expect=1)
    line("step", "link", "S3", "S2")
    assert "stack.broken" not in line("project", "lint", "Stacks", "--json", expect=1)


def test_the_stack_verbs_read_the_topology_first(gated_cli):
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="One line.")
    gated_cli("topology", "show", "Discovery")
    for title in ("A", "B", "C"):
        gated_cli("step", "add", "Discovery", title)
    gated_cli("step", "link", "B", "A")
    gated_cli("stack", "make", "A", "B")
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Changed.")
    for verb in (
        ("stack", "new", "Discovery", "D"),
        ("stack", "make", "C"),
        ("stack", "add", "A", "C"),
        ("stack", "move", "B", "--to", "1"),
        ("stack", "take-out", "B"),
        ("stack", "dissolve", "A"),
    ):
        assert "changed since you read it" in gated_cli(*verb, expect=1), verb
