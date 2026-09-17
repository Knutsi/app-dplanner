"""Tests, checks and runs through the CLI and through the window.

The Qt-free halves — the record shapes, the coverage walk, the run bookkeeping — are in
``test_testing_aspect.py``. This file is the two surfaces over them.
"""

import json

import pytest
from PySide6.QtWidgets import QLabel

from dplanner.domain.commands import (
    AddNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.modules.step_check.aspect import MODULE_ID as CHECK_ID
from dplanner.modules.step_check.aspect import read as check_read
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import MODULE_ID, Test, read, write


def data(text):
    return json.loads(text)


# -- the CLI ------------------------------------------------------------------------------


@pytest.fixture
def cli(cli):
    cli("project", "create", "Widget", "--summary", "The list view")
    cli("step", "add", "widget", "Fix list flicker")
    cli("step", "add", "widget", "Pre-release check", "--after", "Fix list flicker")
    return cli


def test_adding_a_test_mints_a_project_unique_id(cli):
    first = data(
        cli("test", "add", "Fix list flicker", "No flicker", "--text", "1. Look", "--json")
    )
    second = data(cli("test", "add", "Pre-release check", "Rotation", "--json"))
    assert first["id"] == "T100"
    assert second["id"] == "T101"  # Across steps, not per step: a run's results are flat.


def test_a_test_lands_in_the_steps_own_file(cli, workspace):
    cli("test", "add", "Fix list flicker", "No flicker", "--text", "1. Look\n2. Still")
    entry = json.loads(
        (
            workspace / "widget" / "steps" / "fix-list-flicker" / "modules" / "testing.json"
        ).read_text()
    )
    assert entry["tests"] == [{"id": "T100", "title": "No flicker", "body": "1. Look\n2. Still"}]


def test_removing_the_last_test_leaves_no_file(cli, workspace):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "remove", "T100")
    assert not (
        workspace / "widget" / "steps" / "fix-list-flicker" / "modules" / "testing.json"
    ).exists()


def test_a_test_is_found_by_id_or_by_part_of_its_title(cli):
    cli("test", "add", "Fix list flicker", "No flicker on render")
    assert "No flicker" in cli("test", "show", "T100")
    assert "No flicker" in cli("test", "show", "flicker on")


def test_an_ambiguous_name_is_refused_rather_than_guessed(cli):
    cli("test", "add", "Fix list flicker", "Renders fast")
    cli("test", "add", "Fix list flicker", "Renders correctly")
    with pytest.raises(AssertionError, match="matches several tests"):
        cli("test", "show", "Renders")


def test_archiving_is_idempotent_so_a_batch_survives(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    assert "archived" in cli("test", "archive", "T100")
    assert "already archived" in cli("test", "archive", "T100")


# -- test categories, through the CLI ------------------------------------------------------


def test_categories_are_laid_out_before_the_tests_that_will_fill_them(cli):
    """The agent's order of work: read the spec, file the groups, then write the tests."""
    cli("test-category", "add", "Import", "--icon", "layers", "--project", "widget")
    cli("test-category", "add", "Smoke", "--project", "widget")
    listed = data(cli("test-category", "list", "widget", "--json"))
    assert [(c["name"], c["icon"], c["tests"]) for c in listed["categories"]] == [
        ("Import", "layers", 0),
        ("Smoke", "", 0),
    ]
    added = data(
        cli("test", "add", "Fix list flicker", "No flicker", "--category", "Import", "--json")
    )
    assert added["category"] == "Import"
    assert data(cli("test-category", "list", "widget", "--json"))["categories"][0]["tests"] == 1


def test_adding_a_category_twice_is_that_category_so_a_retry_survives(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    assert "already there" in cli("test-category", "add", "import", "--project", "widget")
    assert len(data(cli("test-category", "list", "widget", "--json"))["categories"]) == 1


def test_an_unknown_icon_is_refused_naming_the_set(cli):
    with pytest.raises(AssertionError, match="no such icon"):
        cli("test-category", "add", "Import", "--icon", "spaceship", "--project", "widget")


def test_renaming_a_category_moves_every_test_filed_under_it(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One", "--category", "Import")
    cli("test", "add", "Pre-release check", "Two", "--category", "Import")

    moved = data(
        cli(
            "test-category",
            "set",
            "Import",
            "--rename",
            "Import and export",
            "--json",
            "--project",
            "widget",
        )
    )
    assert moved["moved"] == 2
    listed = data(cli("test", "list", "widget", "--json"))["tests"]
    assert {test["category"] for test in listed} == {"Import and export"}


def test_removing_a_category_unfiles_its_tests_rather_than_deleting_them(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One", "--category", "Import")

    assert "1 test" in cli("test-category", "remove", "Import", "--project", "widget")
    listed = data(cli("test", "list", "widget", "--json"))["tests"]
    assert [test["category"] for test in listed] == [""]
    # Off the list *and* off the tests: one a test still named would come straight back.
    assert data(cli("test-category", "list", "widget", "--json"))["categories"] == []


def test_filing_moves_a_batch_in_one_call(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    for title in ("One", "Two", "Three"):
        cli("test", "add", "Fix list flicker", title)

    cli("test", "file", "T100", "T102", "--category", "Import", "--project", "widget")
    filed = {t["id"]: t["category"] for t in data(cli("test", "list", "widget", "--json"))["tests"]}
    assert filed == {"T100": "Import", "T101": "", "T102": "Import"}

    cli("test", "file", "T100", "--category", "none", "--project", "widget")
    assert data(cli("test", "show", "T100", "--json"))["category"] == ""


def test_filing_sets_both_axes_in_one_call(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One")
    cli(
        "test",
        "file",
        "T100",
        "--category",
        "Import",
        "--sort-key",
        "Customer list view",
        "--project",
        "widget",
    )
    shown = data(cli("test", "show", "T100", "--json"))
    assert (shown["category"], shown["sort_key"]) == ("Import", "Customer list view")


def test_filing_nothing_is_refused_rather_than_done_silently(cli):
    cli("test", "add", "Fix list flicker", "One")
    with pytest.raises(AssertionError, match="nothing to file"):
        cli("test", "file", "T100", "--project", "widget")


def test_filing_under_a_category_that_does_not_exist_is_refused_not_minted(cli):
    cli("test", "add", "Fix list flicker", "One")
    with pytest.raises(AssertionError, match="no category"):
        cli("test", "file", "T100", "--category", "Improt", "--project", "widget")


# -- the sort key, through the CLI ---------------------------------------------------------


def test_a_sort_key_needs_no_catalogue_and_lists_what_is_in_use(cli):
    cli("test", "add", "Fix list flicker", "One", "--sort-key", "Customer list")
    cli("test", "add", "Fix list flicker", "Two", "--sort-key", "Detail view")
    cli("test", "add", "Fix list flicker", "Three")

    listed = data(cli("test", "list", "widget", "--json"))["tests"]
    assert [t["sort_key"] for t in listed] == ["Customer list", "Detail view", ""]
    only = data(cli("test", "list", "widget", "--sort-key", "Detail view", "--json"))["tests"]
    assert [t["id"] for t in only] == ["T101"]


def test_a_list_is_a_run_sheet_by_default_and_flat_on_request(cli):
    """Filed, then ergonomic inside the filing — the order somebody works down."""
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "Loose")
    cli(
        "test",
        "add",
        "Fix list flicker",
        "Second view",
        "--category",
        "Import",
        "--sort-key",
        "Detail view",
    )
    cli(
        "test",
        "add",
        "Fix list flicker",
        "First view",
        "--category",
        "Import",
        "--sort-key",
        "Customer list",
    )

    ordered = [t["id"] for t in data(cli("test", "list", "widget", "--json"))["tests"]]
    assert ordered == ["T102", "T101", "T100"]  # Import (by key), then the unfiled one.
    flat = [t["id"] for t in data(cli("test", "list", "widget", "--flat", "--json"))["tests"]]
    assert flat == ["T100", "T101", "T102"]  # The plan's own order.


def test_a_sort_key_goes_away_with_the_same_word_a_category_does(cli):
    cli("test", "add", "Fix list flicker", "One", "--sort-key", "Customer list")
    assert data(cli("test", "set", "T100", "--sort-key", "none", "--json"))["sort_key"] == ""


def test_setting_a_category_back_to_none_is_a_word_the_terminal_has(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One", "--category", "Import")
    assert data(cli("test", "set", "T100", "--category", "none", "--json"))["category"] == ""


def test_a_test_list_narrows_to_one_category_including_the_unfiled(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One", "--category", "Import")
    cli("test", "add", "Fix list flicker", "Two")

    filed = data(cli("test", "list", "widget", "--category", "Import", "--json"))["tests"]
    assert [test["id"] for test in filed] == ["T100"]
    loose = data(cli("test", "list", "widget", "--category", "Uncategorised", "--json"))["tests"]
    assert [test["id"] for test in loose] == ["T101"]


def test_the_category_lint_stays_quiet_until_the_project_has_categories(cli):
    def checks():
        found = data(cli("project", "lint", "widget", "--json", expect=1))["findings"]
        return [finding for finding in found if finding["check"] == "test.category"]

    cli("test", "add", "Fix list flicker", "One", "--text", "1. Look")
    # A project that has not started filing its tests is not behind on anything.
    assert checks() == []

    cli("test-category", "add", "Import", "--project", "widget")
    unfiled = checks()
    assert len(unfiled) == 1 and "Import" in unfiled[0]["message"]


def test_a_new_step_can_arrive_with_its_first_test_already_filed(cli):
    cli("test-category", "add", "Import", "--project", "widget")
    cli(
        "step",
        "add",
        "widget",
        "Export CSV",
        "--test",
        "Writes a file",
        "--test-category",
        "Import",
    )
    assert data(cli("test", "show", "T100", "--json"))["category"] == "Import"


# -- exporting the roster ------------------------------------------------------------------


def test_exporting_writes_the_tests_filed_by_category(cli, tmp_path):
    cli("test-category", "add", "Import", "--icon", "layers", "--project", "widget")
    cli("test", "add", "Fix list flicker", "One", "--category", "Import", "--text", "1. Look")
    cli("test", "add", "Fix list flicker", "Two")

    out = tmp_path / "tests.md"
    cli("test", "export", "widget", "-o", str(out))
    text = out.read_text()
    assert text.index("## Import") < text.index("## Uncategorised")
    assert "1. Look" in text


def test_exporting_html_gives_one_page_of_expandable_tests(cli, tmp_path):
    cli("test", "add", "Fix list flicker", "One", "--text", "1. Look")
    out = tmp_path / "tests.html"
    cli("test", "export", "widget", "--format", "html", "-o", str(out))
    page = out.read_text()
    assert page.startswith("<!doctype html>") and "<details>" in page


def test_exporting_for_one_audience_says_so_in_the_document(cli):
    cli("test", "add", "Fix list flicker", "By hand", "--audience", "qa")
    cli("test", "add", "Fix list flicker", "Mechanism", "--audience", "technical")
    printed = cli("test", "export", "widget", "--audience", "qa")
    assert "Audience: QA" in printed
    assert "By hand" in printed and "Mechanism" not in printed


def test_an_archived_test_is_out_of_the_roster_until_asked_for(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "archive", "T100")
    assert data(cli("test", "list", "widget", "--json"))["tests"] == []
    assert len(data(cli("test", "list", "widget", "--archived", "--json"))["tests"]) == 1


def test_a_check_gathers_the_tests_behind_it(cli):
    """Reported by `scope show`, the one verb over every kind of collector."""
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "add", "Pre-release check", "Its own test")
    cli("check", "set", "Pre-release check")
    found = data(cli("scope", "show", "Pre-release check", "--json"))
    assert [row["id"] for row in found["direct"]] == ["T100", "T101"]


def test_a_check_is_a_marker_and_clearing_leaves_no_file(cli, workspace):
    cli("check", "set", "Pre-release check")
    path = workspace / "widget" / "steps" / "pre-release-check" / "modules" / "step_check.json"
    assert json.loads(path.read_text())["on"] is True
    cli("check", "clear", "Pre-release check")
    assert not path.exists()


def test_a_run_freezes_its_scope_and_starts_everything_unrecorded(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "add", "Pre-release check", "Rotation")
    cli("check", "set", "Pre-release check")
    started = data(
        cli(
            "test-run", "start", "widget", "--scope", "Pre-release check", "--label", "P3", "--json"
        )
    )
    assert started["tests"] == ["T100", "T101"]
    shown = data(cli("test-run", "show", "widget", "--json"))
    assert shown["counts"] == {"pending": 2, "ok": 0, "failed": 0, "skipped": 0}


def test_marking_records_a_result_and_a_note(cli, workspace):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test-run", "start", "widget", "--label", "P3")
    cli("test-run", "mark", "T100", "failed", "--note", "still flickers")
    entry = json.loads((workspace / "widget" / "modules" / "testing.json").read_text())
    assert entry["runs"][0]["results"] == {"T100": {"status": "failed", "note": "still flickers"}}


def test_marking_pending_leaves_no_entry_behind(cli, workspace):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test-run", "start", "widget")
    cli("test-run", "mark", "T100", "ok")
    cli("test-run", "mark", "T100", "pending")
    entry = json.loads((workspace / "widget" / "modules" / "testing.json").read_text())
    assert "results" not in entry["runs"][0]


def test_marking_needs_an_open_run_and_says_so(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    with pytest.raises(AssertionError, match="no test run is open"):
        cli("test-run", "mark", "T100", "ok")


def test_a_test_outside_the_open_run_is_refused(cli):
    cli("test", "add", "Fix list flicker", "In the run")
    cli("test-run", "start", "widget")
    cli("test", "add", "Pre-release check", "Added afterwards")
    with pytest.raises(AssertionError, match="not in run"):
        cli("test-run", "mark", "T101", "ok")


def test_starting_a_run_closes_the_one_before_it(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test-run", "start", "widget", "--label", "First")
    cli("test-run", "start", "widget", "--label", "Second")
    rows = data(cli("test-run", "list", "widget", "--json"))["runs"]
    assert [(row["label"], row["open"]) for row in rows] == [("First", False), ("Second", True)]


def test_closing_an_already_closed_run_succeeds(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test-run", "start", "widget")
    cli("test-run", "close", "widget")
    assert "already closed" in cli("test-run", "close", "widget", "--run", "R100")


def test_a_run_over_an_empty_scope_is_refused(cli):
    with pytest.raises(AssertionError, match="holds no tests"):
        cli("test-run", "start", "widget")


def test_show_reports_the_latest_result_and_where_it_came_from(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test-run", "start", "widget", "--label", "P3")
    cli("test-run", "mark", "T100", "failed", "--note", "still flickers")
    shown = data(cli("test", "show", "T100", "--json"))
    assert shown["latest"] == {
        "status": "failed",
        "note": "still flickers",
        "run": "R100",
        "run_label": "P3",
    }


def test_step_add_can_author_the_first_test(cli):
    added = cli("step", "add", "widget", "Empty state", "--test", "Says nothing here yet")
    assert "test: T100" in added


def test_lint_names_the_verb_that_closes_each_finding(cli):
    cli("test", "add", "Fix list flicker", "No body yet")
    cli("check", "set", "Pre-release check")
    cli("step", "add", "widget", "Lonely check")
    cli("check", "set", "Lonely check")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    by_check = {row["check"]: row["message"] for row in findings}
    assert "dplanner test set T100" in by_check["test.empty"]
    assert "dplanner check clear 'Lonely check'" in by_check["scope.gathers-nothing"]


# -- who a test is for, through the CLI ---------------------------------------------------


def test_a_test_is_added_with_the_audiences_it_is_written_for(cli):
    added = data(cli("test", "add", "Fix list flicker", "No flicker", "--audience", "qa", "--json"))
    assert added["audiences"] == ["qa"]
    assert data(cli("test", "show", "T100", "--json"))["audiences"] == ["qa"]


def test_an_audience_off_the_list_is_refused_rather_than_stored(cli):
    refused = cli("test", "add", "Fix list flicker", "No flicker", "--audience", "qa2", expect=1)
    assert "qa2" in refused
    assert "technical" in refused  # It names what it would have taken.


def test_setting_an_audience_replaces_the_set_and_none_clears_it(cli):
    cli("test", "add", "Fix list flicker", "No flicker", "--audience", "qa")
    swapped = data(cli("test", "set", "T100", "--audience", "technical", "--json"))
    assert swapped["audiences"] == ["technical"]
    cleared = data(cli("test", "set", "T100", "--audience", "none", "--json"))
    assert cleared["audiences"] == []


def test_none_cannot_be_combined_with_an_audience(cli):
    cli("test", "add", "Fix list flicker", "No flicker", "--audience", "qa")
    refused = cli("test", "set", "T100", "--audience", "none", "--audience", "qa", expect=1)
    assert "cannot be combined" in refused


def test_an_audience_on_its_own_is_something_to_change(cli):
    """``test set`` used to refuse anything but a title or a body."""
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "set", "T100", "--audience", "qa")
    assert data(cli("test", "show", "T100", "--json"))["audiences"] == ["qa"]


def test_listing_narrows_to_an_audience_and_the_unclassified_answer_to_other(cli):
    cli("test", "add", "Fix list flicker", "Mechanism", "--audience", "technical")
    cli("test", "add", "Pre-release check", "By hand", "--audience", "qa")
    cli("test", "add", "Pre-release check", "Nobody said")
    listed = data(cli("test", "list", "widget", "--audience", "qa", "--json"))["tests"]
    assert [row["id"] for row in listed] == ["T101"]
    # Stored, not derived: a caller can tell "nobody said" from a deliberate `other`.
    unsaid = data(cli("test", "list", "widget", "--audience", "other", "--json"))["tests"]
    assert [(row["id"], row["audiences"]) for row in unsaid] == [("T102", [])]


def test_a_run_can_be_opened_over_one_audience(cli):
    cli("test", "add", "Fix list flicker", "Mechanism", "--audience", "technical")
    cli("test", "add", "Pre-release check", "By hand", "--audience", "qa")
    opened = data(cli("test-run", "start", "widget", "--audience", "qa", "--label", "QA", "--json"))
    assert opened["tests"] == ["T101"]


def test_a_run_over_an_audience_nothing_is_written_for_says_so(cli):
    cli("test", "add", "Fix list flicker", "Mechanism", "--audience", "technical")
    refused = cli("test-run", "start", "widget", "--audience", "qa", expect=1)
    assert "written for qa" in refused


def test_lint_asks_a_test_that_does_not_say_who_it_is_for(cli):
    cli("test", "add", "Fix list flicker", "Nobody said", "--text", "1. Look")
    cli("test", "add", "Pre-release check", "Said", "--text", "1. Look", "--audience", "other")
    findings = data(cli("project", "lint", "--json", expect=1))["findings"]
    unclassified = [row for row in findings if row["check"] == "test.audience"]
    assert len(unclassified) == 1  # Only T100: saying `other` out loud is an answer.
    assert "T100" in unclassified[0]["message"]
    assert "dplanner test set T100 --audience qa" in unclassified[0]["message"]


def test_step_add_can_say_who_its_first_test_is_for(cli):
    cli(
        "step",
        "add",
        "widget",
        "Empty state",
        "--test",
        "Says nothing here yet",
        "--test-audience",
        "qa",
    )
    assert data(cli("test", "show", "T100", "--json"))["audiences"] == ["qa"]


def test_editing_a_test_never_drops_the_audience_it_was_given(cli):
    """Every writer rebuilds the record, so each is a chance to lose a field it forgot."""
    cli("test", "add", "Fix list flicker", "No flicker", "--audience", "qa", "--text", "1. Look")
    cli("test", "set", "T100", "--title", "Renamed")
    cli("test", "set", "T100", "--text", "1. Look again")
    cli("test", "archive", "T100")
    cli("test", "unarchive", "T100")
    assert data(cli("test", "show", "T100", "--json"))["audiences"] == ["qa"]


# -- the window --------------------------------------------------------------------------


def select(services, *steps, tests=()):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    nodes = tuple(ContextNode(selection_uri("step", step.id)) for step in steps) + tuple(
        ContextNode(selection_uri("test", test_id)) for test_id in tests
    )
    services.context.set_scope(SCOPE_SELECTION, nodes)


@pytest.fixture
def project(services, make_project):
    return make_project("Widget")


def open_run(services, project):
    found = runs.open_run(runs.read(services.document.project(project.id)))
    assert found is not None
    return found


@pytest.fixture
def step(services, project):
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def test_the_list_verbs_sit_where_a_reader_would_look_for_them(services):
    """Export beside the other exports, the editor beside the project's other test verbs."""
    export_spec = services.actions.spec("tests.export")
    assert (export_spec.menu, export_spec.group, export_spec.submenu) == (
        "File",
        "export",
        "Export",
    )
    editor_spec = services.actions.spec("tests.categories")
    assert (editor_spec.menu, editor_spec.group) == ("Project", "tests")
    # And a data child menu of Step's classify band, so the categories are never a copy.
    data_menu = next(spec for spec in services.actions.data_menus() if spec.id == "test.category")
    assert (data_menu.menu, data_menu.group, data_menu.title) == (
        "Step",
        "classify",
        "Test Category",
    )


def test_the_type_toggles_sit_beside_release_and_agent(services):
    for action_id, order in (("test.toggle", 50), ("check.toggle", 60)):
        spec = services.actions.spec(action_id)
        assert (spec.menu, spec.group, spec.submenu, spec.order) == (
            "Step",
            "classify",
            "Type",
            order,
        )


def test_toggling_test_on_gives_the_step_its_first_test(services, step):
    select(services, step)
    services.actions.run("test.toggle", services.context.current())
    assert [test.id for test in read(step)] == ["T100"]
    assert services.actions.spec("test.toggle").state(services.context.current()).checked
    services.undo.undo()
    assert read(step) == []


def test_toggling_check_on_and_off_is_undoable(services, step):
    select(services, step)
    services.actions.run("check.toggle", services.context.current())
    assert check_read(step)
    services.actions.run("check.toggle", services.context.current())
    assert not check_read(step)


def test_add_test_appends_rather_than_replacing(services, step):
    select(services, step)
    services.actions.run("test.add", services.context.current())
    services.actions.run("test.add", services.context.current())
    assert [test.id for test in read(step)] == ["T100", "T101"]


def test_a_result_verb_with_no_run_open_is_greyed_and_says_why(services, step):
    step.module_data[MODULE_ID] = write([Test("T100", "No flicker")])
    select(services, step, tests=("T100",))
    state = services.actions.spec("test.result_ok").state(services.context.current())
    assert state.enabled is False
    assert state.visible is True  # Disabled teaches the precondition; hidden would not.
    assert "start a test run first" in state.label


def test_marking_a_selection_records_every_one_as_a_single_undo_step(services, project, step):
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])
    started = runs.started([], ["T100", "T101"], label="P3")
    SetModuleDataCommand(project.id, MODULE_ID, runs.write(project, started)).redo(
        services.document
    )

    select(services, step, tests=("T100", "T101"))
    services.actions.run("test.result_ok", services.context.current())
    assert {t: r.status for t, r in open_run(services, project).results.items()} == {
        "T100": "ok",
        "T101": "ok",
    }
    services.undo.undo()
    assert open_run(services, project).results == {}


def test_archiving_spans_the_steps_the_selection_touched_in_one_undo_step(services, project, step):
    other = Step(title="Empty state")
    AddNodeCommand(project.id, other).redo(services.document)
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    other.module_data[MODULE_ID] = write([Test("T101", "Two")])

    select(services, step, other, tests=("T100", "T101"))
    services.actions.run("test.archive", services.context.current())
    assert read(step)[0].archived and read(other)[0].archived
    services.undo.undo()
    assert not read(step)[0].archived and not read(other)[0].archived


def test_close_run_is_greyed_with_a_reason_when_nothing_is_open(services, project, step):
    select(services, step)
    state = services.actions.spec("tests.close_run").state(services.context.current())
    assert state.enabled is False and "no run is open" in state.label


def test_new_run_is_greyed_until_the_project_has_a_test(services, project, step):
    select(services, step)
    state = services.actions.spec("tests.new_run").state(services.context.current())
    assert state.enabled is False and "no tests yet" in state.label
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    assert services.actions.spec("tests.new_run").state(services.context.current()).enabled


# -- the tabs ------------------------------------------------------------------------------


def rows(section):
    """The roster's rows as (id, title) — what the picker above the editor is showing."""
    from dplanner.modules.testing.section import TEST_ID_ROLE

    roster = section.roster
    return [
        (roster.item(row, 0).data(TEST_ID_ROLE), roster.item(row, 1).text())
        for row in range(roster.rowCount())
    ]


@pytest.fixture
def section(services, step):
    from dplanner.modules.testing.section import TestsSection

    section = TestsSection(services.document, services.undo, services.repo.files)
    section.show_target(step.id)
    yield section
    section.dispose()


def test_the_tab_lists_every_test_and_details_the_first(services, project, step, section):
    step.module_data[MODULE_ID] = write([Test("T100", "One", "1. Look"), Test("T101", "Two")])
    section.show_target(step.id)
    started = runs.started([], ["T100", "T101"], label="P3")
    started[-1] = runs.marked(started[-1], "T100", "failed", "still flickers")
    SetModuleDataCommand(project.id, MODULE_ID, runs.write(project, started)).redo(
        services.document
    )
    section.show_target(step.id)

    assert rows(section) == [("T100", "One"), ("T101", "Two")]
    assert section.detail.identity.text() == "T100"
    assert "Failed" in section.detail.chip.text()
    assert "P3" in section.detail.result.text()
    assert "still flickers" in section.detail.result.text()


def test_picking_a_test_swaps_the_editor_under_it(services, step, section):
    step.module_data[MODULE_ID] = write(
        [Test("T100", "One", "first"), Test("T101", "Two", "second")]
    )
    section.show_target(step.id)
    assert section.detail.body.edit.toPlainText() == "first"
    section.roster.selectRow(1)
    assert section.detail.identity.text() == "T101"
    assert section.detail.body.edit.toPlainText() == "second"


def test_a_step_with_no_tests_says_so_instead_of_showing_an_editor(services, step, section):
    assert rows(section) == []
    # isHidden rather than isVisible: nothing here is on a shown window in the suite.
    assert not section.detail.empty.isHidden()
    assert section.detail.title.isHidden()


def test_editing_a_body_writes_through_the_undo_stack(services, step, section):
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    section.show_target(step.id)
    section.detail.body.edit.setPlainText("1. Open the list")
    assert read(step)[0].body == "1. Open the list"
    services.undo.undo()
    assert read(step)[0].body == ""


def test_renaming_a_test_keeps_its_id_and_its_results(services, step, section):
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    section.show_target(step.id)
    section.detail.title.setText("Renamed")
    section.detail.title.editingFinished.emit()
    assert read(step) == [Test("T100", "Renamed")]


def test_adding_a_test_selects_it_so_the_editor_is_ready(services, step, section):
    section._add()
    assert [test_id for test_id, _title in rows(section)] == ["T100"]
    assert section.detail.identity.text() == "T100"
    section._add()
    assert [test_id for test_id, _title in rows(section)] == ["T100", "T101"]
    assert section.detail.identity.text() == "T101"


def scopes():
    """The collectors, wired the way the composition root wires them."""
    from dplanner.modules import _scope_kinds
    from dplanner.modules.feature.aspect import is_feature as feature_read
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    return _scope_kinds(check_read, feature_read, milestone_read)


def covers(services, target):
    from dplanner.modules.testing.section import CoversSection

    section = CoversSection(services.document, scopes(), lambda _step_id: None)
    section.show_target(target)
    return section


def cards(section):
    """The lane's contents, top to bottom: headings as text, tests as their titles."""
    from dplanner.modules.testing.section import _CoveredRow, _GroupHeader

    found = []
    for index in range(section.lane_layout.count() - 1):  # The trailing stretch.
        widget = section.lane_layout.itemAt(index).widget()
        labels = widget.findChildren(QLabel)
        if isinstance(widget, _GroupHeader):
            found.append(("heading", labels[0].text()))
        elif isinstance(widget, _CoveredRow):
            found.append(("test", labels[0].text()))
    return found


def chain(services, project, *titles):
    """Steps in a line, each waiting on the one before it."""
    made: list[Step] = []
    for title in titles:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(services.document)
        if made:
            SetEdgesCommand(step.id, "requires", [made[-1].id]).redo(services.document)
        made.append(step)
    return made


def give(services, step, *test_ids):
    services.document.set_module_data(
        step.id, MODULE_ID, write([Test(test_id, test_id) for test_id in test_ids])
    )


def test_the_covers_tab_lists_what_a_check_waits_on(services, project, step):
    check = Step(title="Pre-release check")
    AddNodeCommand(project.id, check).redo(services.document)
    SetEdgesCommand(check.id, "requires", [step.id]).redo(services.document)
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])

    section = covers(services, check.id)
    assert "2 tests" in section.summary.text()
    # A check stops at nothing, so there is never a second reading to offer.
    assert section.mode_bar.isVisibleTo(section) is False
    assert [kind for kind, _text in cards(section)] == ["test", "test"]
    section.dispose()


def test_a_feature_gathers_only_what_is_new_since_the_previous_one(services, project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write

    login, importer, reporting, export = chain(
        services, project, "Login", "Import", "Reporting", "Export"
    )
    for step in (login, importer, reporting, export):
        give(services, step, f"T{step.title[:2]}")
    for step in (importer, export):
        services.document.set_module_data(step.id, FEATURE_ID, feature_write())

    section = covers(services, export.id)
    # Login and Import went to the Import feature; Export owns Reporting and itself, and
    # reads flat — a feature is the finest grain, so it has no sub-collectors to group by.
    assert cards(section) == [("test", "TRe"), ("test", "TEx")]
    assert "2 tests" in section.summary.text()
    section.dispose()


def test_the_cumulative_reading_is_the_whole_cone(services, project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write

    login, importer, export = chain(services, project, "Login", "Import", "Export")
    for step in (login, importer, export):
        give(services, step, f"T{step.title[:2]}")
    for step in (importer, export):
        services.document.set_module_data(step.id, FEATURE_ID, feature_write())

    section = covers(services, export.id)
    assert section.mode_bar.isVisibleTo(section) is True
    assert cards(section) == [("test", "TEx")]
    section.mode.button(1).setChecked(True)
    section.mode.idClicked.emit(1)
    # Everything behind it, still flat: a feature has no finer collector to group by, and
    # the grouping rule is a property of the kind rather than of the mode.
    assert cards(section) == [("test", "TLo"), ("test", "TIm"), ("test", "TEx")]
    assert "3 tests" in section.summary.text()
    section.dispose()


def test_the_first_feature_in_a_project_is_offered_no_switch(services, project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write

    login, importer = chain(services, project, "Login", "Import")
    give(services, login, "T100")
    services.document.set_module_data(importer.id, FEATURE_ID, feature_write())

    section = covers(services, importer.id)
    # Nothing behind it to hand off to, so both readings are the same answer.
    assert section.mode_bar.isVisibleTo(section) is False
    assert cards(section) == [("test", "T100")]
    section.dispose()


def test_a_release_gathers_the_features_behind_it(services, project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as milestone_write

    importer, first, export, second = chain(services, project, "Import", "v1", "Export", "v2")
    give(services, importer, "TIm")
    give(services, export, "TEx")
    for step in (importer, export):
        services.document.set_module_data(step.id, FEATURE_ID, feature_write())
    for step, label in ((first, "v1"), (second, "v2")):
        services.document.set_module_data(step.id, MILESTONE_ID, milestone_write(label))

    section = covers(services, second.id)
    # v1 took Import; v2 is read as the one feature it adds, and nothing before it.
    assert cards(section) == [("heading", "Feature: Export"), ("test", "TEx")]
    section.dispose()


def test_the_tests_tab_follows_the_aspect(services, step):
    section = next(
        found for found in services.inspector_sections.sections() if found.id == "testing.tab"
    )
    assert section.shown_for(step.id) is False
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    assert section.shown_for(step.id) is True


def test_the_covers_tab_follows_the_check_aspect(services, step):
    from dplanner.modules.step_check.aspect import write as check_write

    section = next(
        found for found in services.inspector_sections.sections() if found.id == "testing.covers"
    )
    assert section.shown_for(step.id) is False
    step.module_data[CHECK_ID] = check_write(True)
    assert section.shown_for(step.id) is True


def test_a_release_scopes_a_run_exactly_as_a_check_does(services, project, step):
    """One walk, two names: a check is a scope you declare, a milestone is one you had."""
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as milestone_write

    section = next(
        found for found in services.inspector_sections.sections() if found.id == "testing.covers"
    )
    step.module_data[MILESTONE_ID] = milestone_write("v1")
    assert section.shown_for(step.id) is True


def test_the_index_folder_offers_all_projects_and_each_one(services, make_project):
    from dplanner.framework.builder import INDEX_PANEL_ID

    make_project("Widget")
    make_project("Search rewrite")
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    folder = next(
        panel.tree.topLevelItem(index)
        for index in range(panel.tree.topLevelItemCount())
        if panel.tree.topLevelItem(index).text(0) == "Tests"
    )
    labels = [folder.child(index).text(0) for index in range(folder.childCount())]
    assert labels == ["All Projects", "Widget", "Search rewrite"]


def test_the_library_wide_tab_lists_every_project_s_tests(services, make_project):
    from dplanner.modules.testing.activity import ALL_TESTS_KIND

    for title in ("Widget", "Search rewrite"):
        project = make_project(title)
        step = Step(title=f"Work in {title}")
        AddNodeCommand(project.id, step).redo(services.document)
        step.module_data[MODULE_ID] = write([Test(f"t{title[0]}", f"A test in {title}")])

    activity = services.tabs.open(ALL_TESTS_KIND)
    table = activity.page.table
    assert table.rowCount() == 2
    assert not table.isColumnHidden(1)  # The project column earns its place here.
    assert "0 of 2 passing" in activity.page.answer.text()


def test_the_tests_tab_can_be_read_by_feature(services, make_project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write
    from dplanner.modules.testing.activity import TESTS_KIND, UNGATHERED

    project = make_project("Widget")
    login, importer, export = chain(services, project, "Login", "Import", "Export")
    orphan = Step(title="Orphan")
    AddNodeCommand(project.id, orphan).redo(services.document)
    for step in (login, importer, export, orphan):
        give(services, step, f"T{step.title[:2]}")
    for step in (importer, export):
        services.document.set_module_data(step.id, FEATURE_ID, feature_write())

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    assert activity.page.controls.is_shown(activity.group_box)  # Offered: two kinds to group by.
    assert table.rowCount() == 4  # Flat by default: four tests, no headings.

    activity.group_box.setCurrentIndex(activity.group_box.findData(FEATURE_ID))
    laid = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert laid == [
        "Feature: Import",
        "TLo",
        "TIm",
        "Feature: Export",
        "TEx",
        UNGATHERED,
        "TOr",
    ]
    # A heading is not a row anybody can mark.
    assert table.test_at(0) is None and table.test_at(1) == "TLo"


def test_a_step_two_features_both_wait_on_is_filed_under_both(services, make_project):
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import write as feature_write
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    shared = Step(title="Shared")
    AddNodeCommand(project.id, shared).redo(services.document)
    give(services, shared, "TSh")
    for title in ("One", "Two"):
        feature = Step(title=title)
        AddNodeCommand(project.id, feature).redo(services.document)
        SetEdgesCommand(feature.id, "requires", [shared.id]).redo(services.document)
        services.document.set_module_data(feature.id, FEATURE_ID, feature_write())

    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.group_box.setCurrentIndex(activity.group_box.findData(FEATURE_ID))
    table = activity.page.table
    laid = [table.item(row, 0).text() for row in range(table.rowCount())]
    # Listed once, under a joint heading: a test in two places is marked twice.
    assert laid.count("TSh") == 1
    assert "Feature: One and Two" in laid


def test_double_clicking_a_test_opens_the_test_not_its_step(services, make_project, monkeypatch):
    """The one exception to *a double-click runs `steps.details`*: here a row **is** a test.

    True in the roll call too, which publishes no selection of its own and so hands the
    verb a context naming exactly the row.
    """
    from dplanner.modules.testing.activity import ALL_TESTS_KIND

    project = make_project("Widget")
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    step.module_data[MODULE_ID] = write([Test("T100", "One")])

    opened: list[str] = []
    monkeypatch.setattr(
        services.actions,
        "run",
        lambda action_id, context: opened.append(f"{action_id}:{context.focus_entity('test')}"),
    )
    activity = services.tabs.open(ALL_TESTS_KIND)
    activity.page.table.cellActivated.emit(0, 0)
    assert opened == ["test.details:T100"]


def test_the_tables_preview_line_reads_as_prose_not_markdown_source():
    from dplanner.modules.testing.table import _preview

    assert _preview("## Setup\n1. Open the list") == "Setup"
    assert _preview("- First bullet\n- Second") == "First bullet"
    assert _preview("1. Open the list") == "1. Open the list"
    assert _preview("") == ""


# -- images in a test body ----------------------------------------------------------------------


def test_a_pasted_image_lands_beside_the_step_and_the_body_references_it(services, step, section):
    """A test's images are the *step's*: `dplanner test attach` has written them to the
    step's testing area all along, and the tab now writes to the same place. The id the
    body editor is bound to is the test's, which names no file area at all — this is the
    assertion that catches keying the attachment on it."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage, QTextCursor

    from dplanner.core.png import encode_rgb
    from dplanner.domain.assets import assets

    step.module_data[MODULE_ID] = write([Test("T100", "One", "Given ")])
    section.show_target(step.id)
    # Binding a document leaves the caret at the top, as setPlainText always does; a person
    # clicks where they want the picture first.
    section.detail.body.edit.moveCursor(QTextCursor.MoveOperation.End)
    mime = QMimeData()
    mime.setImageData(QImage.fromData(encode_rgb(2, 2, 6, b"\x00" * 12)))
    section.detail.body.edit.insertFromMimeData(mime)

    names = assets(services.repo.files(step.id, MODULE_ID))
    assert len(names) == 1
    body = read(services.document.step(step.id))[0].body
    assert body == f"Given ![image]({names[0]})"


def test_the_gallery_is_out_of_the_way_until_the_step_has_a_file(services, step, section):
    """The pane is the tightest surface in the application; an empty gallery costs nothing."""
    from dplanner.domain.assets import attach

    step.module_data[MODULE_ID] = write([Test("T100", "One", "body")])
    section.show_target(step.id)
    gallery = section.detail.body.gallery
    assert gallery is not None and gallery.isHidden()
    attach(services.repo.files(step.id, MODULE_ID), b"png bytes", "figure.png")
    section.show_target(step.id)
    assert not gallery.isHidden()


# -- the Tests tab's strip -----------------------------------------------------------------


def test_the_strip_offers_the_run_verbs_greyed_with_their_reason(services, project, step):
    from dplanner.modules.testing.activity import TESTS_KIND

    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])
    activity = services.tabs.open(TESTS_KIND, project.id)
    controls = activity.page.controls
    ok = controls.button_for("test.result_ok")
    new_run = controls.button_for("tests.new_run")
    assert ok is not None and new_run is not None
    assert not ok.isEnabled() and ok.defaultAction().text() == "Mark Ok — pick a test"
    assert new_run.isEnabled() and not new_run.icon().isNull()

    started = runs.started([], ["T100", "T101"], label="P3")
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, runs.write(project, started)))
    activity.page.table.selectAll()
    # The count says the verb is about to act on more than the eye is on.
    assert ok.isEnabled() and ok.defaultAction().text() == "Mark 2 Tests Ok"
    ok.defaultAction().trigger()
    results = open_run(services, project).results
    assert {test_id: result.status for test_id, result in results.items()} == {
        "T100": "ok",
        "T101": "ok",
    }


def test_a_heading_is_one_plain_row_and_a_milestone_heading_wears_its_shade(services, make_project):
    from dplanner.framework.list_rows import INK_ROLE
    from dplanner.framework.table import row_height
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as milestone_write
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    work, release = chain(services, project, "Work", "Release")
    give(services, work, "TWo")
    services.document.set_module_data(release.id, MILESTONE_ID, milestone_write("v1"))

    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.group_box.setCurrentIndex(activity.group_box.findText("By milestone"))
    table = activity.page.table
    assert table.test_at(0) is None and table.test_at(1) == "TWo"
    # One line however rich the rows under it: a heading as tall as a test reads as a test.
    assert table.rowHeight(0) == row_height(table.font(), rich=False) < table.rowHeight(1)
    assert table.item(0, 0).data(INK_ROLE) is not None


def test_the_roll_call_rebuilds_once_for_a_burst_of_edits(services, make_project, monkeypatch):
    from dplanner.modules.testing.activity import ALL_TESTS_KIND, AllTestsActivity

    project = make_project("Widget")
    work = Step(title="Work")
    AddNodeCommand(project.id, work).redo(services.document)
    rebuilds: list[object] = []
    original = AllTestsActivity._refresh

    def counted(self):
        rebuilds.append(self)
        original(self)

    monkeypatch.setattr(AllTestsActivity, "_refresh", counted)
    services.debounce.set_immediate(False)
    try:
        services.tabs.open(ALL_TESTS_KIND)
        before = len(rebuilds)
        for title in ("one", "two", "three"):
            services.undo.push(SetFieldCommand(work.id, "title", title))
        assert len(rebuilds) == before
        services.debounce.flush_all()
        assert len(rebuilds) == before + 1
    finally:
        services.debounce.set_immediate(True)


def test_a_run_opened_from_the_strip_covers_the_tabs_scope_and_is_shown(
    services, make_project, monkeypatch
):
    from dplanner.framework.dialog import LinePrompt
    from dplanner.modules.step_check.aspect import write as check_write
    from dplanner.modules.testing.activity import TESTS_KIND

    monkeypatch.setattr(LinePrompt, "ask", staticmethod(lambda *_a, **_k: "Smoke"))
    project = make_project("Widget")
    work, gate = chain(services, project, "Work", "Gate")
    other = Step(title="Other")
    AddNodeCommand(project.id, other).redo(services.document)
    give(services, work, "TWo")
    give(services, other, "TOt")
    services.document.set_module_data(gate.id, CHECK_ID, check_write(True))

    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.scope_box.setCurrentIndex(activity.scope_box.findData(gate.id))
    services.actions.run("tests.new_run", services.context.current())
    run = open_run(services, project)
    assert list(run.tests) == ["TWo"] and run.label == "Smoke"
    assert activity.run_box.currentData() == run.id  # The run just opened is what shows.


# -- who a test is for, in the window -----------------------------------------------------


def test_the_audience_filter_narrows_the_table_and_the_lead_says_so(services, make_project):
    from dplanner.modules.testing.activity import NO_MATCH, TESTS_KIND
    from dplanner.modules.testing.table import AUDIENCE_COLUMN

    project = make_project("Widget")
    work, other = chain(services, project, "Work", "Other")
    services.document.set_module_data(
        work.id, MODULE_ID, write([Test("T100", "By hand", audiences=("qa",))])
    )
    services.document.set_module_data(
        other.id, MODULE_ID, write([Test("T101", "Mechanism", audiences=("technical",))])
    )

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    assert table.rowCount() == 2
    assert not table.isColumnHidden(AUDIENCE_COLUMN)
    assert table.item(0, AUDIENCE_COLUMN).text() == "QA"

    activity.page.audience.set_active(["qa"])
    assert [table.test_at(row) for row in range(table.rowCount())] == ["T100"]
    # The tab leads with a count, so a count that has lost rows has to say it has.
    assert "1 of 2 shown" in activity.page.detail.text()

    activity.page.audience.set_active(["other"])
    assert table.rowCount() == 0
    assert activity.page.empty.label.text() == NO_MATCH

    activity.page.audience.clear()
    assert table.rowCount() == 2
    assert "shown" not in activity.page.detail.text()


# -- categories in the window --------------------------------------------------------------


def select_project(services, project):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )


def categorise(services, project, *catalog):
    from dplanner.modules.testing.filing import Category, write_catalog

    found = services.document.project(project.id)
    services.document.set_module_data(
        project.id, MODULE_ID, write_catalog(found, [Category(*entry) for entry in catalog])
    )


def filed(services, step, *pairs):
    services.document.set_module_data(
        step.id,
        MODULE_ID,
        write([Test(test_id, test_id, category=category) for test_id, category in pairs]),
    )


def test_the_tests_tab_opens_filed_by_category_once_the_project_has_any(services, make_project):
    from dplanner.modules.testing.activity import BY_CATEGORY, TESTS_KIND
    from dplanner.modules.testing.table import CATEGORY_COLUMN

    project = make_project("Widget")
    work, other = chain(services, project, "Work", "Other")
    categorise(services, project, ("Import", "layers"), ("Smoke",))
    filed(services, work, ("T100", "Import"), ("T101", ""))
    filed(services, other, ("T102", "Smoke"))

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    assert activity.group_box.currentData() == BY_CATEGORY
    laid = [table.item(row, 0).text() for row in range(table.rowCount())]
    # The catalogue's own order, with the unfiled last — never alphabetical.
    assert laid == ["Import", "T100", "Smoke", "T102", "Uncategorised", "T101"]
    # The column would repeat the heading over every row under it.
    assert table.isColumnHidden(CATEGORY_COLUMN)


def test_the_roster_prints_the_id_a_body_would_quote(services, make_project):
    """Without it the table named every fact about a test but the word it is called by."""
    from dplanner.modules.testing.activity import TESTS_KIND
    from dplanner.modules.testing.table import ID_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")

    table = services.tabs.open(TESTS_KIND, project.id).page.table
    assert not table.isColumnHidden(ID_COLUMN)
    assert table.item(0, ID_COLUMN).text() == "T100"
    # The step it hangs off is still on every cell, because the selection is that pair.
    assert table.step_at(0) == work.id


def test_a_row_under_a_category_heading_is_indented_under_it(services, make_project):
    """The reading a folding heading is for: which group the row you are on belongs to."""
    from dplanner.framework.table import GROUP_INDENT
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import", "layers"))
    filed(services, work, ("T100", "Import"))

    table = services.tabs.open(TESTS_KIND, project.id).page.table
    assert table.is_heading(0) and not table.is_heading(1)
    assert table.delegate.indent(table.model().index(0, 0)) == 0  # The heading itself.
    assert table.delegate.indent(table.model().index(1, 0)) == GROUP_INDENT


def test_a_project_with_no_categories_opens_flat_rather_than_on_one_empty_heading(
    services, make_project
):
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")

    activity = services.tabs.open(TESTS_KIND, project.id)
    assert activity.group_box.currentData() == ""
    assert activity.page.table.rowCount() == 1  # No heading.


def test_a_grouping_the_reader_picked_survives_the_project_gaining_categories(
    services, make_project
):
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"))

    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.group_box.setCurrentIndex(activity.group_box.findData(""))  # Flat, deliberately.
    assert activity.group_box.currentData() == ""

    categorise(services, project, ("Import",), ("Smoke",))
    activity._refresh()
    assert activity.group_box.currentData() == ""  # Their answer stands.


def test_a_category_heading_folds_and_stays_folded_across_a_rebuild(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"), ("T101", "Import"))

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    assert table.group_at(0) == "Import"
    assert not table.isRowHidden(1)

    table.toggle_group("Import")
    assert table.isRowHidden(1) and table.isRowHidden(2)
    assert not table.isRowHidden(0)  # The heading is what you open it again with.

    # A rebuild is what a host does on every change; a fold kept by row number would go.
    SetFieldCommand(work.id, "title", "Renamed").redo(services.document)
    activity._refresh()
    assert table.collapsed() == {"Import"} and table.isRowHidden(1)


def test_a_category_is_set_from_the_step_menus_data_child(services, project, step):
    from dplanner.modules.testing.filing import category_of

    categorise(services, project, ("Import",))
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])
    select(services, step, tests=("T100", "T101"))

    menu = services.window.dynamic_menubar.data_menu("test.category")
    entries = [action.text() for action in menu.actions() if action.text()]
    assert entries[:2] == ["Import", "Uncategorised"]
    menu.actions()[0].trigger()

    filed_now = [category_of(test) for test in read(services.document.step(step.id))]
    assert filed_now == ["Import", "Import"]
    assert services.undo.can_undo()  # One step, both tests.


def test_the_category_menu_says_so_when_nothing_is_picked(services, project, step):
    categorise(services, project, ("Import",))
    menu = services.window.dynamic_menubar.data_menu("test.category")
    entries = [(action.text(), action.isEnabled()) for action in menu.actions() if action.text()]
    assert ("Pick a test first", False) in entries
    # The editor's verb is rendered, never copied.
    assert any("Categories" in text for text, _on in entries)


def menu_shape(popup):
    """The popup's shape: separators as "|", child menus as (title, [their entries])."""
    rendered: list[object] = []
    for action in popup.actions():
        if action.isSeparator():
            rendered.append("|")
        elif action.menu() is not None:
            rendered.append((action.text(), menu_shape(action.menu())))
        else:
            rendered.append(action.text())
    return rendered


def test_a_right_click_on_a_test_leads_with_the_results_and_offers_the_step_menu(
    services, project, step
):
    """A row here is a test: the verbs about *it* lead, and the step's are one level down."""
    from dplanner.framework.action_menu import build_menu
    from dplanner.modules.testing.activity import TESTS_KIND

    step.module_data[MODULE_ID] = write([Test("T100", "Signs in")])
    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    select(services, step, tests=("T100",))

    def rendered(**where):
        return menu_shape(build_menu(services.actions, services.context, "Step", table, **where))

    band = rendered(submenu="Test", group="test_result")
    assert band[0].startswith("Mark Ok")  # What a run records, in the strip's own order.

    shape = menu_shape(activity._test_menu(table))
    assert shape[: len(band)] == band
    assert shape[len(band)] == "|"
    title, under = shape[len(band) + 1]
    # And the child *is* the Step menu — the same render the canvas's right-click gets.
    assert title == "Step" and under == rendered()
    assert len(shape) == len(band) + 2  # Nothing else: this popup is those two things.


def test_a_greyed_result_still_says_why_in_the_menu_a_right_click_renders(services, project, step):
    """Disabled, never hidden, with the reason in the label — the one presenter policy."""
    from dplanner.modules.testing.activity import TESTS_KIND

    step.module_data[MODULE_ID] = write([Test("T100", "Signs in")])
    activity = services.tabs.open(TESTS_KIND, project.id)
    select(services, step, tests=("T100",))

    first = activity._test_menu(activity.page.table).actions()[0]
    assert not first.isEnabled() and "start a test run first" in first.text()


def test_right_clicking_a_category_heading_picks_the_whole_group(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"), ("T101", "Import"), ("T102", ""))

    table = services.tabs.open(TESTS_KIND, project.id).page.table
    assert table.tests_under(0) == ["T100", "T101"]
    assert table.tests_under(1) == []  # A test row is not a group.


# -- the sort key in the window ------------------------------------------------------------


def keyed(services, step, *triples):
    services.document.set_module_data(
        step.id,
        MODULE_ID,
        write(
            [
                Test(test_id, test_id, category=category, sort_key=key)
                for test_id, category, key in triples
            ]
        ),
    )


def test_a_category_is_ordered_by_its_tests_sort_keys(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND
    from dplanner.modules.testing.table import SORT_KEY_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    keyed(
        services,
        work,
        ("T100", "Import", "Detail view"),
        ("T101", "Import", "Customer list"),
        ("T102", "Import", ""),
        ("T103", "Import", "Customer list"),
    )

    table = services.tabs.open(TESTS_KIND, project.id).page.table
    shown = [table.test_at(row) for row in range(table.rowCount()) if table.test_at(row)]
    # Adjacency is the win: both customer-list tests together, and the keyless one last.
    assert shown == ["T101", "T103", "T100", "T102"]
    assert not table.isColumnHidden(SORT_KEY_COLUMN)
    assert table.item(1, SORT_KEY_COLUMN).text() == "Customer list"


def test_ergonomic_order_is_on_by_default_and_can_be_switched_off(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    keyed(services, work, ("T100", "", "Zebra"), ("T101", "", "Apple"))

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    assert activity.ergonomic.isChecked()
    assert [table.test_at(row) for row in range(2)] == ["T101", "T100"]

    activity.ergonomic.trigger()  # A checkable verb toggles and fires its slot.
    assert not activity.ergonomic.isChecked()
    assert [table.test_at(row) for row in range(2)] == ["T100", "T101"]  # The plan's order.


def test_the_sort_key_column_appears_the_day_a_project_uses_one(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND
    from dplanner.modules.testing.table import SORT_KEY_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")

    table = services.tabs.open(TESTS_KIND, project.id).page.table
    assert table.isColumnHidden(SORT_KEY_COLUMN)


def test_a_sort_key_is_set_from_the_step_menus_data_child(services, project, step):
    categorise(services, project, ("Import",))
    keyed(services, step, ("T100", "Import", "Customer list"), ("T101", "Import", ""))
    select(services, step, tests=("T101",))

    menu = services.window.dynamic_menubar.data_menu("test.sort_key")
    entries = [action.text() for action in menu.actions() if action.text()]
    # What is already in use, then the way to take it away, then the way to mint one.
    assert entries == ["Customer list", "No sort key", "New Sort Key…"]
    menu.actions()[0].trigger()
    assert [test.sort_key for test in read(services.document.step(step.id))] == [
        "Customer list",
        "Customer list",
    ]


def test_the_step_panel_offers_the_keys_in_use_and_commits_a_typed_one(
    services, project, step, section
):
    other = Step(title="Other")
    AddNodeCommand(project.id, other).redo(services.document)
    keyed(services, other, ("T200", "", "Customer list"))
    keyed(services, step, ("T100", "", ""))
    section.show_target(step.id)

    picker = section.detail.sort_key
    assert [picker.itemText(i) for i in range(picker.count())] == ["Customer list"]
    picker.setEditText("Detail view")
    section.detail._commit_sort_key()
    assert read(services.document.step(step.id))[0].sort_key == "Detail view"


# -- the Test panel ---------------------------------------------------------------------------


def open_tests_tab(services, project):
    """The project's Tests tab, current — where its Test panel lives."""
    from dplanner.modules.testing.activity import TESTS_KIND

    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.on_activated()
    return activity


def the_panel(activity):
    return activity.page.side_panel.content


def pick_test(services, step, test_id):
    """A test picked the way every view picks one: with the step it hangs off.

    Never the test alone — an id is minted per project, so ``T100`` on its own names one
    test in each of them and the panel has nothing to choose by.
    """
    select(services, step, tests=(test_id,))
    return services.context.current()


def test_the_panel_shows_one_picked_test_and_steps_aside_for_none(services, project, step):
    step.module_data[MODULE_ID] = write(
        [Test("T100", "Signs in", body="1. Open it.\n2. It must work.", category="Smoke")]
    )
    panel = the_panel(open_tests_tab(services, project))

    assert panel.show_context(pick_test(services, step, "T100"))
    assert panel.head.title.text() == "Signs in"
    assert "Smoke" in panel.head.filed.text() and "Fix list flicker" in panel.head.filed.text()
    # Rendered, not printed: a numbered list is a numbered list on a surface you run from.
    assert "<ol" in panel.body.toHtml() or "<li" in panel.body.toHtml()

    from dplanner.framework.context import Context

    assert not panel.show_context(Context({}))


def test_the_panel_steps_aside_when_several_tests_are_picked(services, project, step):
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])
    panel = the_panel(open_tests_tab(services, project))
    select(services, step, tests=("T100", "T101"))
    assert not panel.show_context(services.context.current())


def test_show_step_opens_the_step_this_test_hangs_off(services, project, step, monkeypatch):
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    panel = the_panel(open_tests_tab(services, project))
    panel.show_context(pick_test(services, step, "T100"))

    opened: list[str] = []
    monkeypatch.setattr(
        services.actions,
        "run",
        lambda action_id, context: opened.append(f"{action_id}:{context.focus_entity('step')}"),
    )
    panel.step_verb.trigger()
    assert opened == [f"steps.details:{step.id}"]


def test_next_moves_the_tables_selection_so_a_run_can_be_worked_down(services, make_project):
    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    keyed(services, work, ("T100", "", "Apple"), ("T101", "", "Banana"))
    activity = open_tests_tab(services, project)
    panel = the_panel(activity)
    activity.pick_test("T100")

    assert panel.next_verb.isEnabled() and not panel.previous_verb.isEnabled()
    panel.next_verb.trigger()
    # The *table* moved, and the tab fed the panel what it picked.
    assert activity.page.table.selected_tests() == ["T101"]
    assert panel.head.title.text() == "T101"
    assert not panel.next_verb.isEnabled()  # The end of the list says so.
    assert "list" in panel.next_verb.toolTip()


def test_the_test_panel_stands_in_the_tests_tab_not_in_the_window(services, project, step):
    """A panel that belongs to a tab: one per Tests tab, fed by that tab's own pick, so a
    tab in the background never follows the tab in front. The dock offers no copy, so
    View ▸ Panels has no entry for it either."""
    from dplanner.modules.testing.panel import TestPanel

    activity = open_tests_tab(services, project)
    assert isinstance(the_panel(activity), TestPanel)
    assert not any(spec.id.startswith("testing.") for spec in services.panels.panels())
    with pytest.raises(KeyError):
        services.actions.spec("appshell.panel_testing.test")


def test_the_panel_reaches_the_top_of_the_tab(services, project):
    """The seam runs the full height of the tab: the panel stands beside the caption and
    the strip as well as the roster, as the Problems list does beside the canvas."""
    from PySide6.QtCore import QPoint

    activity = open_tests_tab(services, project)
    page = activity.page
    page.resize(1400, 800)
    services.actions.run("tests.side_panel", services.context.current())
    page.layout().activate()
    page.side_panel.split.layout()  # A splitter lays out on activation too.
    assert page.side_panel.frame.mapTo(page, QPoint(0, 0)).y() == 0


def test_two_projects_tests_tabs_each_carry_their_own_panel(services, make_project):
    """Ids are minted per *project*, so `T100` names a test in every one of them — and a
    tab's panel shows its own tab's pick, whichever tab is in front."""
    first = make_project("Alpha")
    second = make_project("Beta")
    (early,) = chain(services, first, "Alpha work")
    (late,) = chain(services, second, "Beta work")
    services.document.set_module_data(early.id, MODULE_ID, write([Test("T100", "Alpha's test")]))
    services.document.set_module_data(late.id, MODULE_ID, write([Test("T100", "Beta's test")]))

    alpha = open_tests_tab(services, first)
    beta = open_tests_tab(services, second)
    beta.pick_test("T100")
    assert the_panel(beta).head.title.text() == "Beta's test"

    services.tabs.focus(alpha)
    alpha.pick_test("T100")
    assert the_panel(alpha).head.title.text() == "Alpha's test"
    assert the_panel(beta).head.title.text() == "Beta's test"  # A background tab keeps its own.


def test_switching_tabs_takes_the_panel_with_the_tab_and_brings_it_back(services, make_project):
    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")
    tests = open_tests_tab(services, project)
    tests.pick_test("T100")
    services.actions.run("test.details", services.context.current())
    frame = tests.page.side_panel.frame
    assert frame.isVisibleTo(services.window)

    graph = services.tabs.open("project", project.id)
    assert services.tabs.current_activity() is graph
    assert not frame.isVisibleTo(services.window)  # Gone with its tab …
    assert the_panel(tests).head.title.text() == "T100"  # … and keeping its content.

    services.tabs.focus(tests)
    assert frame.isVisibleTo(services.window)


def test_the_panel_preference_is_one_answer_for_every_tests_tab(services, make_project):
    """Remembered per user, like the graph's: a Tests tab opened later stands as this one
    does, and the panel's own way out is the same verb, so it is written once."""
    from dplanner.framework.user_config import get_global

    first = make_project("Alpha")
    second = make_project("Beta")
    spec = services.actions.spec("tests.side_panel")
    assert (spec.menu, spec.group) == ("Project", "tests")

    alpha = open_tests_tab(services, first)
    assert alpha.page.side_panel.frame.isHidden()
    assert not spec.state(services.context.current()).checked

    services.actions.run("tests.side_panel", services.context.current())
    assert not alpha.page.side_panel.frame.isHidden()
    assert spec.state(services.context.current()).checked
    assert alpha.page.side_panel.button.isChecked()
    assert get_global(MODULE_ID, "side_panel") is True

    beta = open_tests_tab(services, second)
    assert not beta.page.side_panel.frame.isHidden()

    alpha.page.side_panel.frame.close_button.click()
    assert alpha.page.side_panel.frame.isHidden() and beta.page.side_panel.frame.isHidden()
    assert get_global(MODULE_ID, "side_panel") is False


def test_a_test_with_no_step_beside_it_is_nothing_to_show(services, project, step):
    """And the verb agrees, so a reveal can never put an empty panel on screen."""
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    alone = Context({SCOPE_SELECTION: (ContextNode(selection_uri("test", "T100")),)})
    assert not the_panel(open_tests_tab(services, project)).show_context(alone)
    assert not services.actions.spec("test.details").state(alone).enabled


def test_double_clicking_a_row_names_the_rows_own_step(services, make_project):
    """A row is a test and its step is a column, so the double-click publishes the pair —
    which is what makes the panel show that row rather than a namesake elsewhere."""
    project = make_project("Widget")
    work, other = chain(services, project, "Work", "Other")
    give(services, work, "T100")
    give(services, other, "T101")

    activity = open_tests_tab(services, project)
    row = next(
        index
        for index in range(activity.page.table.rowCount())
        if activity.page.table.test_at(index) == "T101"
    )
    activity.page.table.cellActivated.emit(row, 0)

    current = services.context.current()
    assert current.selected_entity("test") == "T101"
    assert current.selected_entity("step") == other.id
    assert the_panel(activity).head.title.text() == "T101"


def test_the_roll_call_names_the_rows_step_too_and_hosts_its_own_panel(services, make_project):
    """The one view holding several projects at once, so it is the one that cannot get
    away with naming a test alone — and a single click there feeds its own panel."""
    from dplanner.modules.testing.activity import ALL_TESTS_KIND

    first = make_project("Alpha")
    second = make_project("Beta")
    (early,) = chain(services, first, "Alpha work")
    (late,) = chain(services, second, "Beta work")
    services.document.set_module_data(early.id, MODULE_ID, write([Test("T100", "Alpha's test")]))
    services.document.set_module_data(late.id, MODULE_ID, write([Test("T100", "Beta's test")]))

    activity = services.tabs.open(ALL_TESTS_KIND)
    activity.on_activated()
    table = activity.page.table
    row = next(index for index in range(table.rowCount()) if table.step_at(index) == late.id)
    table.selectRow(row)
    assert services.context.current().selected_entity("step") == late.id
    assert the_panel(activity).head.title.text() == "Beta's test"

    table.cellActivated.emit(row, 0)
    assert not activity.page.side_panel.frame.isHidden()


def test_double_clicking_a_row_reveals_the_panel(services, make_project):
    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")

    activity = open_tests_tab(services, project)  # A real double-click activates the pane first.
    frame = activity.page.side_panel.frame
    assert frame.isHidden()  # Off until asked for.
    activity.page.table.cellActivated.emit(0, 0)
    assert not frame.isHidden()


def test_test_details_from_another_tab_opens_the_projects_tests_tab_and_its_panel(
    services, make_project
):
    """The panel lives in the Tests tab, so the verb run from anywhere else goes there."""
    from dplanner.modules.testing.activity import TestsActivity

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")
    services.tabs.open("project", project.id)

    services.actions.run("test.details", pick_test(services, work, "T100"))
    current = services.tabs.current_activity()
    assert isinstance(current, TestsActivity) and current.project_id == project.id
    assert current.page.table.selected_tests() == ["T100"]
    assert not current.page.side_panel.frame.isHidden()


# -- the category editor -------------------------------------------------------------------


def editor(services, project, **kwargs):
    from dplanner.modules.testing.categories_dialog import CategoriesDialog

    return CategoriesDialog(services.document, services.undo, project.id, **kwargs)


def test_the_editor_counts_what_each_category_holds_before_anything_moves(services, make_project):
    from dplanner.modules.testing.categories_dialog import COUNT_COLUMN, NAME_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",), ("Smoke",))
    filed(services, work, ("T100", "Import"), ("T101", "Import"), ("T102", ""))

    dialog = editor(services, project)
    rows = [
        (dialog.table.item(row, NAME_COLUMN).text(), dialog.table.item(row, COUNT_COLUMN).text())
        for row in range(dialog.table.rowCount())
    ]
    assert rows == [("Import", "2"), ("Smoke", "0"), ("Uncategorised", "1")]
    dialog.deleteLater()


def test_the_editor_writes_nothing_until_it_is_saved(services, make_project):
    from dplanner.modules.testing.categories_dialog import NAME_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"))

    dialog = editor(services, project)
    dialog.table.edited.emit(0, NAME_COLUMN, "Import and export")
    # Still on disk as it was: the edit is on the copy, so no view rebuilds behind it.
    assert read(services.document.step(work.id))[0].category == "Import"

    dialog._save()
    assert read(services.document.step(work.id))[0].category == "Import and export"
    assert not services.undo.can_redo()


def test_saving_a_rename_is_one_undo_step_over_every_step_it_touched(services, make_project):
    from dplanner.modules.testing.categories_dialog import NAME_COLUMN

    project = make_project("Widget")
    work, other = chain(services, project, "Work", "Other")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"))
    filed(services, other, ("T101", "Import"))

    dialog = editor(services, project)
    dialog.table.edited.emit(0, NAME_COLUMN, "In")
    dialog._save()

    services.undo.undo()
    assert read(services.document.step(work.id))[0].category == "Import"
    assert read(services.document.step(other.id))[0].category == "Import"


def test_the_editor_refuses_a_save_that_would_leave_two_categories_sharing_a_name(
    services, make_project
):
    from dplanner.modules.testing.categories_dialog import NAME_COLUMN

    project = make_project("Widget")
    categorise(services, project, ("Import",), ("Smoke",))
    dialog = editor(services, project)
    dialog.table.edited.emit(1, NAME_COLUMN, "import")

    assert dialog.primary() is not None and not dialog.primary().isEnabled()
    assert "share a name" in dialog.status.text()
    dialog.deleteLater()


def test_removing_a_category_in_the_editor_unfiles_its_tests(services, make_project):
    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    categorise(services, project, ("Import",))
    filed(services, work, ("T100", "Import"))

    dialog = editor(services, project)
    dialog.table.selectRow(0)
    dialog._rows[0].removed = True  # What Remove does once the question is answered.
    dialog._fill()
    dialog._save()

    assert read(services.document.step(work.id))[0].category == ""
    from dplanner.modules.testing.filing import read_catalog

    assert read_catalog(services.document.project(project.id)) == []


def test_a_categorys_icon_is_picked_from_the_offered_set(services, make_project):
    from dplanner.modules.testing.filing import ICONS

    project = make_project("Widget")
    categorise(services, project, ("Import",))
    dialog = editor(services, project)
    dialog._set_icon(dialog._rows[0], ICONS[0])
    dialog._save()

    from dplanner.modules.testing.filing import read_catalog

    assert read_catalog(services.document.project(project.id))[0].icon == ICONS[0]


# -- exporting from the window -------------------------------------------------------------


def test_the_export_verb_writes_what_the_tab_is_showing(
    services, make_project, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    from dplanner.modules.testing.activity import TESTS_KIND

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    services.document.set_module_data(
        work.id,
        MODULE_ID,
        write(
            [
                Test("T100", "By hand", audiences=("qa",)),
                Test("T101", "Mechanism", audiences=("technical",)),
            ]
        ),
    )
    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.page.audience.set_active(["qa"])

    out = tmp_path / "tests.md"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "Markdown (*.md)"))
    )
    select_project(services, project)
    services.actions.run("tests.export", services.context.current())

    text = out.read_text()
    assert "Audience: QA" in text
    assert "By hand" in text and "Mechanism" not in text


def test_the_export_verb_is_greyed_with_its_reason_on_a_project_with_no_tests(services, project):
    select_project(services, project)
    state = services.actions.spec("tests.export").state(services.context.current())
    assert not state.enabled and "no tests yet" in (state.label or "")


def test_an_unclassified_test_answers_to_other_and_hides_the_column(services, make_project):
    from dplanner.modules.testing.activity import TESTS_KIND
    from dplanner.modules.testing.table import AUDIENCE_COLUMN

    project = make_project("Widget")
    (work,) = chain(services, project, "Work")
    give(services, work, "T100")

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    # Nothing here is classified, so the column would say "Other" all the way down.
    assert table.isColumnHidden(AUDIENCE_COLUMN)
    activity.page.audience.set_active(["other"])
    assert table.rowCount() == 1  # It still answers the filter: it is what it reads as.


def test_the_step_panel_files_a_test_from_the_projects_own_categories(
    services, project, step, section
):
    categorise(services, project, ("Import",), ("Smoke",))
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    section.show_target(step.id)

    picker = section.detail.category
    assert [picker.itemText(i) for i in range(picker.count())] == [
        "Uncategorised",
        "Import",
        "Smoke",
    ]
    picker.setCurrentIndex(picker.findData("Smoke"))
    assert read(services.document.step(step.id))[0].category == "Smoke"

    services.undo.undo()
    assert read(services.document.step(step.id))[0].category == ""


def test_a_test_filed_under_something_the_catalogue_lost_still_shows_it(
    services, project, step, section
):
    """The value is the test's; a picker that quietly moved it would be an edit."""
    step.module_data[MODULE_ID] = write([Test("T100", "One", category="Gone")])
    section.show_target(step.id)
    assert section.detail.category.currentText() == "Gone"


def test_ticking_an_audience_is_one_undoable_step_per_test(services, step, section):
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])
    section.show_target(step.id)

    section.detail.audience_boxes["qa"].setChecked(True)
    section.detail.audience_boxes["technical"].setChecked(True)
    assert read(step)[0].audiences == ("qa", "technical")

    services.undo.undo()
    assert read(step)[0].audiences == ("qa",)  # Two toggles, two steps — never coalesced.
    services.undo.redo()
    section.detail.audience_boxes["qa"].setChecked(False)
    assert read(step)[0].audiences == ("technical",)


def test_the_boxes_say_what_is_stored_and_the_note_says_what_it_reads_as(services, step, section):
    step.module_data[MODULE_ID] = write([Test("T100", "One")])
    section.show_target(step.id)
    assert not any(box.isChecked() for box in section.detail.audience_boxes.values())
    assert "reads as Other" in section.detail.result.text()

    section.detail.audience_boxes["other"].setChecked(True)
    assert read(step)[0].audiences == ("other",)
    # Said out loud now, so the note that asks for it goes.
    assert "reads as Other" not in section.detail.result.text()


def test_typing_in_the_body_keeps_the_audience(services, step, section):
    """The body field rebuilds the record on every keystroke — the easiest place to lose it."""
    step.module_data[MODULE_ID] = write([Test("T100", "One", audiences=("qa",))])
    section.show_target(step.id)
    section.detail.body.edit.setPlainText("1. Look at it.")
    assert read(step)[0].audiences == ("qa",)


def test_the_empty_editor_teaches_the_shape_the_cli_gates_on():
    """Two surfaces, one vocabulary: `dplanner test format` is the document a test body is
    refused without, and the window's placeholder must not show a different shape."""
    from dplanner.modules.testing.format import guide
    from dplanner.modules.testing.section import BODY_PLACEHOLDER

    for heading in ("## Preconditions", "## Steps"):
        assert heading in BODY_PLACEHOLDER and heading in guide()


# -- tests that have gone stale -----------------------------------------------------------


@pytest.fixture
def stale(cli):
    """A done step with a test that was run, and then a decision that moved under it."""
    cli("test", "add", "Fix list flicker", "No flicker", "--text", "1. Look")
    cli("test-run", "start", "widget", "--label", "P1")
    cli("test-run", "mark", "T100", "ok")
    cli("test-run", "close", "widget")
    cli("status", "set", "Fix list flicker", "done")
    return cli


def findings(cli, *argv):
    return data(cli("test", "review", "widget", "--json", *argv))["findings"]


def test_a_test_not_run_since_a_later_note_is_reported(stale):
    stale(
        "note",
        "add",
        "widget",
        "decision",
        "rows may arrive late",
        "--step",
        "Fix list flicker",
        "--made",
        "2099-01-01",
    )
    found = findings(stale)
    assert [row["test"] for row in found] == ["T100"]
    assert found[0]["note"] == "N1" and found[0]["label"] == "decision"
    # The advice names the verbs that close it, the way `coverage review`'s rows do.
    assert "test-run start" in found[0]["advice"] and "test set T100" in found[0]["advice"]


def test_a_note_older_than_the_last_run_is_not_a_finding(stale):
    """The run already answered for it — that is the whole question this verb asks."""
    stale(
        "note",
        "add",
        "widget",
        "decision",
        "settled before the run",
        "--step",
        "Fix list flicker",
        "--made",
        "2000-01-01",
    )
    assert findings(stale) == []


def test_only_a_decision_or_a_spec_change_unsettles_a_test(stale):
    """A handoff says where the code lives; it makes no claim about what a test proves."""
    for label in ("handoff", "later", "post-project"):
        stale(
            "note",
            "add",
            "widget",
            label,
            f"a {label} note",
            "--step",
            "Fix list flicker",
            "--made",
            "2099-01-01",
        )
    assert findings(stale) == []


def test_a_step_still_being_worked_on_is_not_behind_its_tests(cli):
    """Work in progress is *meant* to be ahead of its tests; only a done step has settled."""
    cli("test", "add", "Fix list flicker", "No flicker", "--text", "1. Look")
    cli(
        "note",
        "add",
        "widget",
        "decision",
        "rows may arrive late",
        "--step",
        "Fix list flicker",
        "--made",
        "2099-01-01",
    )
    assert findings(cli) == []  # pending
    cli("status", "set", "Fix list flicker", "in-progress")
    assert findings(cli) == []
    cli("status", "set", "Fix list flicker", "done")
    assert [row["test"] for row in findings(cli)] == ["T100"]


def test_a_test_nobody_ever_ran_is_behind_every_note_on_its_step(cli):
    cli("test", "add", "Fix list flicker", "Never run", "--text", "1. Look")
    cli("status", "set", "Fix list flicker", "done")
    cli(
        "note",
        "add",
        "widget",
        "spec-change",
        "the header is optional",
        "--step",
        "Fix list flicker",
        "--made",
        "2000-01-01",
    )
    found = findings(cli)
    # Older than any run there could have been, and still a finding: nothing has
    # established this test against it.
    assert [(row["test"], row["last_run"]) for row in found] == [("T100", "")]
    assert "never run" in found[0]["what"]


def test_an_archived_test_is_off_the_roster_and_out_of_the_review(stale):
    stale(
        "note",
        "add",
        "widget",
        "decision",
        "rows may arrive late",
        "--step",
        "Fix list flicker",
        "--made",
        "2099-01-01",
    )
    assert len(findings(stale)) == 1
    stale("test", "archive", "T100")
    assert findings(stale) == []


def test_a_superseded_note_names_its_test_once_behind_the_note_that_replaced_it(stale):
    stale(
        "note",
        "add",
        "widget",
        "decision",
        "rows may arrive late",
        "--step",
        "Fix list flicker",
        "--made",
        "2099-01-01",
    )
    stale(
        "note",
        "add",
        "widget",
        "decision",
        "rows arrive in order after all",
        "--step",
        "Fix list flicker",
        "--made",
        "2099-02-02",
        "--supersedes",
        "N1",
    )
    found = findings(stale)
    assert [row["test"] for row in found] == ["T100"]  # Once, not twice.
    assert found[0]["note"] == "N2"


def test_a_project_with_nothing_stale_says_so(stale):
    from dplanner.modules.testing.cli import REVIEW_CLEAR

    assert REVIEW_CLEAR in stale("test", "review", "widget")
