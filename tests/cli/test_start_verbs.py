"""``dplanner start …`` — the step a plan begins from, and the walks that stop at it.

The shape the default topology recommends is work fanning out of one origin in parallel.
Before the marker, every feature's walk reached that origin and lint called it gathered by
all of them at once; these tests hold the plan to the other answer.

No ``qapp`` fixture: the aspect and its verbs are Qt-free by rule.
"""

import json

import pytest

from dplanner.domain.model import Step
from dplanner.planning.start import MODULE_ID, read, summary, write


def data(text):
    return json.loads(text)


@pytest.fixture
def cli(cli):
    """Project start, fanning out into three features in parallel, all gathered by v1."""
    cli("project", "create", "Widget")
    cli("step", "add", "widget", "Project start", "--start")
    for title in ("Import", "Export", "Reporting"):
        cli("step", "add", "widget", title, "--after", "Project start", "--feature")
        cli("test", "add", title, f"{title} works")
    cli("step", "add", "widget", "v1", "--after", "Import", "--after", "Export")
    cli("step", "link", "v1", "Reporting")
    cli("milestone", "set", "v1", "--label", "v1")
    return cli


def shape_findings(cli):
    """What lint says about the graph's shape and its scopes — the plan's other gaps
    (descriptions, estimates) are not this file's subject."""
    rows = data(cli("project", "lint", "widget", "--json", expect=1))["findings"]
    return [row for row in rows if row["check"].startswith(("graph.", "scope."))]


# -- the aspect and its verbs --------------------------------------------------------------


def test_the_entry_is_a_bare_marker():
    step = Step(title="Project start")
    assert read(step) is False and summary(step) == ""
    step.module_data[MODULE_ID] = write(True)
    assert step.module_data[MODULE_ID] == {"on": True, "format": 1}
    assert read(step) is True and summary(step) == "start"
    assert write(False) == {}  # which removes the file


def test_set_and_clear_say_so_and_survive_being_repeated(cli):
    assert "no longer the start" in cli("start", "clear", "Project start")
    assert "not the start" in cli("start", "clear", "Project start")
    assert data(cli("start", "set", "Project start", "--json"))["start"] is True
    assert "already the start" in cli("start", "set", "Project start")


def test_step_add_authors_the_start_in_the_same_call(cli):
    cli("start", "clear", "Project start")
    added = data(cli("step", "add", "widget", "Kick-off", "--start", "--json"))
    assert added["start"] is True


def test_a_start_that_waits_on_something_is_refused_at_birth(cli):
    said = cli("step", "add", "widget", "Second", "--after", "Import", "--start", expect=1)
    assert "a start waits on nothing" in said
    assert "Second" not in cli("step", "list", "widget")  # The transaction wrote nothing.


# -- the walks stop at it ------------------------------------------------------------------


def test_a_plan_fanning_out_of_its_start_names_nothing_about_its_shape(cli):
    assert shape_findings(cli) == []


def test_without_the_marker_the_origin_is_gathered_by_every_feature(cli):
    """The finding the marker exists to retire — kept, because on a plan that has not said
    where it begins, it is the truth."""
    cli("start", "clear", "Project start")
    shared = [row for row in shape_findings(cli) if row["check"] == "scope.shared"]
    assert [row["title"] for row in shared] == ["Project start"]
    assert "'Import' and 'Export' and 'Reporting'" in shared[0]["message"]


def test_a_feature_after_the_start_has_nothing_before_it(cli):
    """The start stops the walk, but it is no earlier collector: nothing to name as *after*
    and no second reading to offer."""
    found = data(cli("scope", "show", "Import", "--json"))
    assert [row["step_title"] for row in found["direct"]] == ["Import"]
    assert found["after"] == []
    assert "after" not in cli("scope", "show", "Import")


def test_a_check_still_stands_for_everything_the_start_included(cli):
    """A check owns nothing, so it stops at nothing — and the start's own tests, which no
    feature can gather, are not reported as work nobody planned."""
    cli("test", "add", "Project start", "The repository builds")
    cli("step", "add", "widget", "Gate", "--after", "v1")
    cli("check", "set", "Gate")
    found = data(cli("scope", "show", "Gate", "--json"))
    gathered = [row["id"] for group in found["gathers"] for row in group["tests"]]
    assert len(gathered + found["direct"]) == 4
    assert "The repository builds" in [row["title"] for row in found["direct"]]
    assert shape_findings(cli) == []


def test_a_start_marked_as_a_milestone_is_a_milestone_that_gathers_nothing(cli):
    """Being the start does not stop a step being another kind: its walk is empty, and the
    finding that says so names the verb."""
    cli("milestone", "set", "Project start", "--label", "M0")
    found = shape_findings(cli)
    assert [(row["check"], row["title"]) for row in found] == [
        ("scope.gathers-nothing", "Project start")
    ]
    assert "dplanner milestone clear 'Project start'" in found[0]["message"]


# -- graph.start ---------------------------------------------------------------------------


def test_a_start_that_waits_on_something_is_reported_with_the_way_out(cli):
    cli("step", "add", "widget", "Kick-off")
    cli("step", "link", "Project start", "Kick-off")
    found = [row for row in shape_findings(cli) if row["check"] == "graph.start"]
    assert [row["title"] for row in found] == ["Project start"]
    assert "dplanner step unlink 'Project start' 'Kick-off'" in found[0]["message"]
    assert "dplanner start clear 'Project start'" in found[0]["message"]


def test_every_start_is_reported_when_a_plan_has_two(cli):
    cli("step", "add", "widget", "Also a start", "--start")
    found = [row for row in shape_findings(cli) if row["check"] == "graph.start"]
    assert sorted(row["title"] for row in found) == ["Also a start", "Project start"]
    by_title = {row["title"]: row["message"] for row in found}
    assert "'Project start'" in by_title["Also a start"]
    assert "'Also a start'" in by_title["Project start"]
    assert all("dplanner start clear" in message for message in by_title.values())
