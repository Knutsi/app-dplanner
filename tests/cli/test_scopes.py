"""``dplanner scope show`` and the lint findings the same walk answers.

The verb belongs to no feature: a check, a feature and a milestone are one derivation asked
with a different stopping rule, so there is one report over all three and this file is
where it is held to that.
"""

import json

import pytest


def data(text):
    return json.loads(text)


@pytest.fixture
def cli(cli):
    """A chain: Login → Import → Reporting → Export → v1, with a test on each step."""
    cli("project", "create", "Widget")
    previous = None
    for title in ("Login", "Import", "Reporting", "Export", "v1"):
        if previous is None:
            cli("step", "add", "widget", title)
        else:
            cli("step", "add", "widget", title, "--after", previous)
        previous = title
    for title in ("Login", "Import", "Reporting", "Export"):
        cli("test", "add", title, f"{title} works")
    cli("feature", "set", "Import")
    cli("feature", "set", "Export")
    cli("milestone", "set", "v1", "--label", "v1")
    return cli


# -- what a collector gathers --------------------------------------------------------------


def test_a_feature_gathers_its_own_work_up_to_the_previous_feature(cli):
    found = data(cli("scope", "show", "Export", "--json"))
    assert found["kind"] == "feature"
    assert [row["step_title"] for row in found["direct"]] == ["Reporting", "Export"]
    assert found["gathers"] == []  # A feature is the finest grain; it reads flat.
    assert [row["title"] for row in found["after"]] == ["Import"]


def test_a_release_is_read_as_the_features_it_adds(cli):
    found = data(cli("scope", "show", "v1", "--json"))
    assert found["kind"] == "step_milestone"
    titles = {group["title"]: [row["id"] for row in group["tests"]] for group in found["gathers"]}
    assert sorted(titles) == ["Feature: Export", "Feature: Import"]
    assert found["direct"] == []  # Every step behind v1 belongs to one of its features.


def test_a_check_stands_for_everything_behind_it(cli):
    cli("step", "add", "widget", "Gate", "--after", "v1")
    cli("check", "set", "Gate")
    found = data(cli("scope", "show", "Gate", "--json"))
    gathered = [row["id"] for group in found["gathers"] for row in group["tests"]]
    assert len(gathered + found["direct"]) == 4
    assert found["after"] == []  # A check stops at nothing, so nothing is left out.


def test_cumulative_reaches_past_the_previous_collector(cli):
    truncated = data(cli("scope", "show", "Export", "--json"))
    whole = data(cli("scope", "show", "Export", "--cumulative", "--json"))
    assert len(truncated["direct"]) == 2
    assert whole["cumulative"] is True
    assert len(whole["direct"]) == 4


def test_a_plain_step_is_not_a_scope(cli):
    assert "not a scope" in cli("scope", "show", "Login", expect=1)


def test_the_report_names_the_groups_and_what_came_before(cli):
    text = cli("scope", "show", "v1")
    assert "Feature: Import" in text and "Feature: Export" in text
    text = cli("scope", "show", "Export")
    assert "after Import" in text


# -- lint ----------------------------------------------------------------------------------


def test_a_collector_with_nothing_behind_it_is_reported(cli):
    cli("step", "add", "widget", "Lonely feature")
    cli("feature", "set", "Lonely feature")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    message = next(row["message"] for row in findings if row["check"] == "scope.gathers-nothing")
    assert "dplanner feature clear 'Lonely feature'" in message


def test_a_step_two_features_both_wait_on_is_reported(cli):
    cli("step", "add", "widget", "Shared")
    cli("test", "add", "Shared", "Shared works")
    cli("step", "link", "Import", "Shared")
    cli("step", "link", "Export", "Shared")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    shared = [row for row in findings if row["check"] == "scope.shared"]
    assert [row["title"] for row in shared] == ["Shared"]
    assert "'Import' and 'Export'" in shared[0]["message"]


def test_a_step_with_tests_that_no_feature_gathers_is_reported(cli):
    cli("step", "add", "widget", "Orphan")
    cli("test", "add", "Orphan", "Orphan works")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    orphans = [row for row in findings if row["check"] == "scope.ungathered"]
    assert [row["title"] for row in orphans] == ["Orphan"]


def test_a_project_with_no_features_is_not_told_it_is_missing_them(cli):
    cli("feature", "clear", "Import")
    cli("feature", "clear", "Export")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    assert not [row for row in findings if row["check"] == "scope.ungathered"]
