"""``dplanner auto-progress …`` — parallel work handed to a step that collects it.

Three agents work side by side; a fourth step collects them, landing their branches and
setting them done. The links into it auto-progress, so it may start as soon as they read
ready for review. These tests walk that flow from the terminal, the way an agent shaping
a plan and the agents executing it both reach it.

No ``qapp`` fixture: the aspect and its verbs are Qt-free by rule.
"""

import json

import pytest

from dplanner.domain.model import Step
from dplanner.modules.auto_progress.aspect import (
    MODULE_ID,
    flagged,
    read,
    remap_for_paste,
    with_sources,
    write,
)


def data(text):
    return json.loads(text)


@pytest.fixture
def cli(cli):
    """Three agent steps in parallel, a plain prerequisite P, and C waiting on all four."""
    cli("project", "create", "Widget")
    for title in ("A1", "A2", "A3", "P"):
        cli("step", "add", "widget", title)
        cli("agent", "on", title)
    cli("step", "add", "widget", "C", "--after", "A1", "--after", "A2", "--after", "P")
    cli("agent", "on", "C")
    return cli


def progression(cli):
    found = data(cli("progression", "show", "widget", "--json"))
    return {
        "ready": [row["title"] for row in found["ready"]],
        "upcoming": [row["title"] for row in found["upcoming"]],
    }


# -- the aspect -----------------------------------------------------------------------------


def test_a_listed_id_counts_only_while_the_link_exists():
    """Read through the edge, never repaired: a link removed leaves its id inert."""
    step = Step(title="C")
    step.edges["requires"] = ["a", "b"]
    step.module_data[MODULE_ID] = write(["a", "b", "gone"])
    assert step.module_data[MODULE_ID] == {"from": ["a", "b", "gone"], "format": 1}
    assert flagged(step) == {"a", "b"}
    step.edges["requires"] = ["b"]
    assert flagged(step) == {"b"} and read(step) == ("a", "b", "gone")
    assert with_sources(step, ["b"], on=False) == write(["a", "gone"])
    assert with_sources(step, ["c", "a"], on=True) == write(["b", "gone", "c", "a"])
    assert write([]) == {}  # which removes the file


def test_a_paste_carries_the_ids_of_the_copies_and_drops_the_rest():
    step = Step(title="C copy")
    step.module_data[MODULE_ID] = write(["a", "outside"])
    remap_for_paste(None, [step], {"a": "a2", "c": "c2"})  # type: ignore[arg-type]
    assert read(step) == ("a2",)
    remap_for_paste(None, [step], {})  # type: ignore[arg-type]
    assert MODULE_ID not in step.module_data


# -- the verbs ------------------------------------------------------------------------------


def test_a_collector_is_ready_once_its_sources_are_ready_for_review(cli):
    """The T109 flow: C collects A1, A2 and A3 and still waits on a plain P."""
    cli("auto-progress", "set", "C", "A1", "on")
    cli("auto-progress", "set", "C", "A2", "on")
    cli("auto-progress", "set", "C", "A3", "on")  # Not linked yet: `on` makes the link.
    cli("status", "set", "P", "done")
    cli("status", "set", "A1", "ready-for-review")
    cli("status", "set", "A2", "ready-for-review")
    assert "C" in progression(cli)["upcoming"]
    cli("status", "set", "A3", "ready-for-review")
    assert progression(cli)["ready"] == ["C"]


def test_a_plain_source_still_holds_a_collector(cli):
    for source in ("A1", "A2"):
        cli("auto-progress", "set", "C", source, "on")
        cli("status", "set", source, "ready-for-review")
    cli("status", "set", "P", "ready-for-review")
    assert "C" in progression(cli)["upcoming"]


def test_on_makes_the_missing_link_in_one_command_and_off_leaves_it_plain(cli):
    said = cli("auto-progress", "set", "C", "A3", "on")
    assert "may start once" in said
    shown = data(cli("step", "show", "C", "--json"))
    a3 = data(cli("step", "show", "A3", "--json"))["id"]
    assert a3 in shown["requires"] and shown["auto_progress"] == [a3]
    assert "already auto-progress" in cli("auto-progress", "set", "C", "A3", "on")
    assert "plain" in cli("auto-progress", "set", "C", "A3", "off")
    shown = data(cli("step", "show", "C", "--json"))
    assert a3 in shown["requires"] and shown["auto_progress"] == []
    assert "already plain" in cli("auto-progress", "set", "C", "A3", "off")


def test_on_refuses_a_link_the_model_would_refuse(cli):
    said = cli("auto-progress", "set", "A1", "C", "on", expect=1)
    assert "cannot link" in said and "cycle" in said


def test_list_names_each_collector_and_where_its_sources_stand(cli):
    cli("auto-progress", "set", "C", "A1", "on")
    cli("status", "set", "A1", "ready-for-review")
    listed = data(cli("auto-progress", "list", "widget", "--json"))["collectors"]
    assert [row["title"] for row in listed] == ["C"]
    assert [(s["title"], s["status"]) for s in listed[0]["collects"]] == [
        ("A1", "ready-for-review")
    ]
    assert "A1 — ready for review" in cli("auto-progress", "list", "widget")


def test_step_add_flags_every_after_link(cli):
    added = data(
        cli(
            "step",
            "add",
            "widget",
            "D",
            "--after",
            "A1",
            "--after",
            "A2",
            "--auto-progress",
            "--json",
        )
    )
    assert len(added["auto_progress"]) == 2
    said = cli("step", "add", "widget", "E", "--auto-progress", expect=1)
    assert "--after" in said
    assert "E" not in cli("step", "list", "widget")  # The transaction wrote nothing.


def test_the_graph_and_step_show_mark_the_links(cli):
    cli("auto-progress", "set", "C", "A1", "on")
    chart = cli("project", "graph", "widget", "--short")
    # --short names nodes by key: A1, A2, A3 are S1, S2, S3; P is S4 and C is S5.
    assert "s1 ==> s5" in chart and "s2 --> s5" in chart and "s4 --> s5" in chart
    assert "A1 (auto-progress)" in cli("step", "show", "C")


def test_lint_names_a_collector_no_agent_will_pick_up(cli):
    cli("auto-progress", "set", "C", "A1", "on")
    cli("agent", "off", "C")
    rows = data(cli("project", "lint", "widget", "--json", expect=1))["findings"]
    found = [row for row in rows if row["check"] == "auto-progress.waiter"]
    assert [row["subject"] for row in found] == [data(cli("step", "show", "C", "--json"))["id"]]
    assert "dplanner agent on" in found[0]["message"]
    assert "auto-progress set" in found[0]["message"]


def test_duplicating_sources_and_collector_keeps_the_flags_on_the_copies(cli):
    cli("auto-progress", "set", "C", "A1", "on")
    cli("step", "duplicate", "A1", "C")
    listed = data(cli("auto-progress", "list", "widget", "--json"))["collectors"]
    assert len(listed) == 2
    original, copy = listed
    assert original["collects"][0]["step"] != copy["collects"][0]["step"]
    assert copy["collects"][0]["title"] == "A1"


def test_setting_the_flag_is_a_graph_edit_behind_the_topology(gated_cli):
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Parallel, then collect.")
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "A")
    gated_cli("step", "add", "Discovery", "C")
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Changed.")
    out = gated_cli("auto-progress", "set", "C", "A", "on", expect=1)
    assert "changed since you read it" in out
