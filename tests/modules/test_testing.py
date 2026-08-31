"""Tests, checks and runs through the CLI and through the window.

The Qt-free halves — the record shapes, the coverage walk, the run bookkeeping — are in
``test_testing_aspect.py``. This file is the two surfaces over them.
"""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
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


def test_an_archived_test_is_out_of_the_roster_until_asked_for(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "archive", "T100")
    assert data(cli("test", "list", "widget", "--json"))["tests"] == []
    assert len(data(cli("test", "list", "widget", "--archived", "--json"))["tests"]) == 1


def test_a_check_gathers_the_tests_behind_it(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "add", "Pre-release check", "Its own test")
    cli("check", "set", "Pre-release check")
    found = data(cli("check", "show", "Pre-release check", "--json"))
    assert [row["id"] for row in found["tests"]] == ["T100", "T101"]


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
    assert "dplanner check clear 'Lonely check'" in by_check["check.covers-nothing"]


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


def test_the_type_toggles_sit_beside_release_and_agent(services):
    for action_id, order in (("test.toggle", 40), ("check.toggle", 50)):
        spec = services.actions.spec(action_id)
        assert (spec.menu, spec.group, spec.submenu, spec.order) == ("Step", "type", "Type", order)


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
    SetModuleDataCommand(project.id, MODULE_ID, runs.write(started)).redo(services.document)

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
    """The list's rows as (id, title) — what the picker above the editor is showing."""
    from dplanner.modules.testing.view import TEST_ID_ROLE

    return [
        (section.list.item(i).data(TEST_ID_ROLE), section.list.item(i).text())
        for i in range(section.list.count())
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
    SetModuleDataCommand(project.id, MODULE_ID, runs.write(started)).redo(services.document)
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
    section.list.setCurrentRow(1)
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


def test_the_covers_tab_lists_what_a_check_waits_on(services, project, step):
    from dplanner.modules.testing.section import CoversSection

    check = Step(title="Pre-release check")
    AddNodeCommand(project.id, check).redo(services.document)
    SetEdgesCommand(check.id, "requires", [step.id]).redo(services.document)
    step.module_data[MODULE_ID] = write([Test("T100", "One"), Test("T101", "Two")])

    section = CoversSection(services.document, lambda _step_id: None)
    section.show_target(check.id)
    assert "2 tests" in section.summary.text()
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
    """One walk, two names: a check is a scope you declare, a release is one you had."""
    from dplanner.modules.step_release.aspect import MODULE_ID as RELEASE_ID
    from dplanner.modules.step_release.aspect import write as release_write

    section = next(
        found for found in services.inspector_sections.sections() if found.id == "testing.covers"
    )
    step.module_data[RELEASE_ID] = release_write("v1")
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


def test_double_clicking_a_test_anywhere_opens_its_step(services, make_project, monkeypatch):
    """The one gesture across every table: a row opens `steps.details` on its own step."""
    from dplanner.modules.testing.activity import ALL_TESTS_KIND

    project = make_project("Widget")
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    step.module_data[MODULE_ID] = write([Test("T100", "One")])

    opened: list[str] = []
    monkeypatch.setattr(
        services.actions,
        "run",
        lambda action_id, context: opened.append(f"{action_id}:{context.focus_entity('step')}"),
    )
    activity = services.tabs.open(ALL_TESTS_KIND)
    activity.page.table.cellActivated.emit(0, 0)
    assert opened == [f"steps.details:{step.id}"]


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
