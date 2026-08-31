"""The order view: waves and dates on screen, and the seams it reaches other features through."""

import json
from datetime import date

import pytest
from PySide6.QtCore import QDate

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.domain.schedule import format_date
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.modules.step_order.view import (
    ACCUMULATED_COLUMN,
    ASPECTS_COLUMN,
    DATE_COLUMN,
    ESTIMATE_COLUMN,
    MILESTONE_ROLE,
    MILESTONE_ROW_EXTRA,
    ROW_HEIGHT,
    SINCE_MILESTONE_COLUMN,
    TITLE_COLUMN,
    _MilestoneRowDelegate,
)


@pytest.fixture
def project(services, make_project):
    """A → B, A → C, and D waiting on both B and C: three waves, one with two steps."""
    library = services.document
    project = make_project("Discovery")
    for title in ("A", "B", "C", "D"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    a, b, c, d = project.steps
    for waiter, sources in ((b, [a]), (c, [a]), (d, [b, c])):
        SetEdgesCommand(waiter.id, "requires", [s.id for s in sources]).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("order", project.id)


def rows_on_screen(tab):
    """Every row as (index, step, wave) — what a person reads off the table."""
    table = tab.table
    return [
        tuple(table.item(row, column).text() for column in (0, 1, 2))
        for row in range(table.rowCount())
    ]


# -- what it shows ---------------------------------------------------------------------------


def test_the_steps_are_a_numbered_table_in_order(services, project, tab):
    """The topological index is the first column, because the first thing wanted from a
    sorted sequence is a position."""
    assert rows_on_screen(tab) == [
        ("1", "A", "Ready to start"),
        ("2", "B", "Wave 2"),
        ("3", "C", "Wave 2"),
        ("4", "D", "Wave 3"),
    ]


def test_the_table_follows_the_graph(services, project, tab):
    """Nothing is stored, so a new edge renumbers the table with no recompute to remember."""
    _a, b, _c, _d = project.steps
    services.undo.push(SetEdgesCommand(b.id, "requires", []))
    assert rows_on_screen(tab)[:2] == [
        ("1", "A", "Ready to start"),
        ("2", "B", "Ready to start"),
    ]

    services.undo.undo()
    assert rows_on_screen(tab)[1] == ("2", "B", "Wave 2")


def test_a_row_carries_what_the_aspects_say(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand

    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "step_ticket", {"key": "WID-14", "format": 1}))
    assert "WID-14" in tab.table.item(0, ASPECTS_COLUMN).text()


def test_the_estimate_has_a_column_and_is_not_repeated_in_the_summary(services, project, tab):
    """One number, one place: the trailing summary is for aspects with no column of their own."""
    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))

    assert tab.table.item(0, ESTIMATE_COLUMN).text() == "3d"
    assert "3d" not in tab.table.item(0, ASPECTS_COLUMN).text()


def test_a_release_row_is_marked_and_keeps_its_name(services, project, tab):
    """Every cell flags the row for the delegate; the name still reads in the summary."""
    from dplanner.modules.step_milestone.aspect import write

    d = project.steps[3]  # The last of its block — the rule under it closes the work above.
    services.undo.push(SetModuleDataCommand(d.id, "step_milestone", write("MVP")))

    table = tab.table
    release_row = 3
    assert all(
        table.item(release_row, column).data(MILESTONE_ROLE) == "MVP"
        for column in range(table.columnCount())
    )
    # Emphasis by size, not weight — DESIGN.md's Tables: bold shouts in a quiet table.
    title = table.item(release_row, TITLE_COLUMN).font()
    plain = table.item(0, TITLE_COLUMN).font()
    assert not title.bold()
    assert title.pointSizeF() > plain.pointSizeF()
    assert "MVP" in table.item(release_row, ASPECTS_COLUMN).text()
    assert isinstance(table.itemDelegate(), _MilestoneRowDelegate)


def test_a_release_date_is_highlighted(services, project, tab):
    from dplanner.modules.step_milestone.aspect import write

    d = project.steps[3]
    services.undo.push(SetModuleDataCommand(d.id, "estimation", {"days": 2.0, "format": 1}))
    services.undo.push(SetModuleDataCommand(d.id, "step_milestone", write("MVP")))

    from PySide6.QtCore import Qt

    item = tab.table.item(3, DATE_COLUMN)
    assert item.font().pointSizeF() > tab.table.item(0, TITLE_COLUMN).font().pointSizeF()
    assert not item.font().bold()
    # No faded brush was set: the date keeps the palette's full-strength, live foreground.
    assert item.data(Qt.ItemDataRole.ForegroundRole) is None


def test_a_release_row_gets_air_and_a_plain_row_does_not(services, project, tab):
    from dplanner.modules.step_milestone.aspect import write

    d = project.steps[3]
    services.undo.push(SetModuleDataCommand(d.id, "step_milestone", write("MVP")))

    assert tab.table.rowHeight(3) == ROW_HEIGHT + MILESTONE_ROW_EXTRA
    assert tab.table.rowHeight(0) == ROW_HEIGHT
    assert not tab.table.item(0, TITLE_COLUMN).data(MILESTONE_ROLE)


def test_the_days_accumulate_down_the_order(services, project, tab):
    for step, days in zip(project.steps, (1.0, 2.0, 3.0, 4.0), strict=True):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))

    accumulated = [tab.table.item(row, ACCUMULATED_COLUMN).text() for row in range(4)]
    assert accumulated == ["1d", "3d", "6d", "2w"]


def test_column_headers_read_from_the_left(services, project, tab):
    """DESIGN.md's Tables: headers are left-aligned, not Qt's centred default."""
    from PySide6.QtCore import Qt

    assert tab.table.horizontalHeader().defaultAlignment() & Qt.AlignmentFlag.AlignLeft


def test_a_release_row_says_how_long_since_the_one_before(services, project, tab):
    """The span a milestone closes: its accumulated total minus the previous milestone's. The
    first milestone measures from the start of the plan."""
    from dplanner.modules.step_milestone.aspect import write

    for step, days in zip(project.steps, (1.0, 2.0, 3.0, 4.0), strict=True):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))
    services.undo.push(SetModuleDataCommand(project.steps[2].id, "step_milestone", write("v1")))
    services.undo.push(SetModuleDataCommand(project.steps[3].id, "step_milestone", write("v2")))

    column = [tab.table.item(row, SINCE_MILESTONE_COLUMN).text() for row in range(4)]
    assert column == ["", "", "6d", "4d"]
    assert not tab.table.isColumnHidden(SINCE_MILESTONE_COLUMN)


def test_the_since_milestone_column_waits_for_a_release_and_an_estimate(services, project, tab):
    """A column of blanks says less than an absent one — same rule as the Date column."""
    from dplanner.modules.step_milestone.aspect import write

    assert tab.table.isColumnHidden(SINCE_MILESTONE_COLUMN)
    services.undo.push(SetModuleDataCommand(project.steps[0].id, "estimation", {"days": 3.0}))
    assert tab.table.isColumnHidden(SINCE_MILESTONE_COLUMN)  # Nothing yet to measure to.
    services.undo.push(SetModuleDataCommand(project.steps[3].id, "step_milestone", write("MVP")))
    assert not tab.table.isColumnHidden(SINCE_MILESTONE_COLUMN)


def test_the_title_column_wears_the_step_kind_icons(services, project, tab):
    """The canvas medallions' vocabulary, read off the same wiring: a milestone wears the tag,
    a step with an agent instruction the spark, a plain step nothing."""
    from dplanner.domain.commands import EditTextCommand
    from dplanner.domain.model import TextEdit
    from dplanner.modules.step_milestone.aspect import write

    services.undo.push(SetModuleDataCommand(project.steps[3].id, "step_milestone", write("MVP")))
    services.undo.push(
        EditTextCommand(TextEdit(project.steps[0].id, "step_agent_instruction", 0, "", "Do it."))
    )

    table = tab.table
    assert not table.item(3, TITLE_COLUMN).icon().isNull()
    assert not table.item(0, TITLE_COLUMN).icon().isNull()
    assert table.item(1, TITLE_COLUMN).icon().isNull()


def test_there_is_no_date_column_until_something_is_estimated(services, project, tab):
    """A column of blanks says less than an absent one. The blank is now "nobody sized this"
    rather than "nobody dated the project" — a project with no start date starts today."""
    assert tab.table.isColumnHidden(DATE_COLUMN)

    services.undo.push(SetModuleDataCommand(project.steps[0].id, "estimation", {"days": 3.0}))
    assert not tab.table.isColumnHidden(DATE_COLUMN)

    tab.start_bar.date.setDate(QDate(2026, 9, 7))  # A Monday.
    # Through the shared formatter, so the table and the terminal cannot read differently.
    assert tab.table.item(0, DATE_COLUMN).text() == format_date(date(2026, 9, 9))


def test_the_bar_opens_on_today_and_writes_nothing(services, project, tab):
    """A project nobody dated starts today — derived, so opening a tab still dirties nothing.
    Storing it would be wrong by tomorrow, and would dirty the workspace to say so."""
    assert tab.start_bar.date.date().toPython() == date.today()
    assert "estimation" not in project.module_data
    assert not services.undo.can_undo()


def test_the_start_date_is_written_to_the_project_and_undoable(services, project, tab):
    """The bar belongs to another module; the order view only lends it a place to stand."""
    tab.start_bar.date.setDate(QDate(2026, 9, 7))
    assert project.module_data["estimation"]["start"] == "2026-09-07"

    services.undo.undo()
    assert "estimation" not in project.module_data


def test_the_tab_is_titled_for_its_project_and_follows_a_rename(services, project, tab):
    from dplanner.domain.commands import SetFieldCommand

    assert tab.title == "Discovery — Order"
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert "Discovery Phase — Order" in [a.title for a in services.tabs.activities()]


def test_a_deleted_project_takes_its_order_tab_with_it(services, project, tab):
    from dplanner.domain.commands import RemoveNodeCommand

    services.undo.push(RemoveNodeCommand(project.id))
    assert services.tabs.activities() == []


# -- the two seams ---------------------------------------------------------------------------


def test_selecting_a_step_publishes_it_so_the_step_verbs_target_it(services, project, tab):
    """This view never learns the Step menu exists; it publishes and the verbs follow."""
    tab.table.selectRow(0)

    context = services.context.current()
    assert context.selected_entities("step") == [project.steps[0].id]
    assert services.actions.spec("steps.rename").state(context).enabled


def test_activating_a_step_opens_its_details(services, project, tab, monkeypatch):
    """The other seam: the row runs the same ``steps.details`` verb the Step menu offers,
    against a context naming exactly that row's step."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    tab.table.cellActivated.emit(0, 1)
    assert shown == [project.steps[0].id]


def test_reveal_in_graph_shows_the_step_on_the_canvas(services, project, tab):
    """Double-click no longer reveals, so the verb has to: it opens the project tab and
    selects the step there, from a table with no canvas in sight."""
    tab.table.selectRow(0)
    services.actions.run("steps.reveal", services.context.current())

    graph = next(
        a for a in services.tabs.activities() if a.uri.startswith("app://activity/project")
    )
    assert graph._scene.selected_step() == project.steps[0].id


def test_activating_a_row_that_is_not_there_does_nothing(services, project, tab):
    tab.table.cellActivated.emit(99, 1)
    assert [a.uri for a in services.tabs.activities()] == [tab.uri]


def test_the_action_opens_it_for_the_focused_project(services, project):
    from dplanner.framework.context import ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("order.open", services.context.current())
    assert [a.uri for a in services.tabs.activities()] == [f"app://activity/order/{project.id}"]


def test_the_verb_sits_in_the_step_menu_only(services):
    """The Project side is the index tree's Order row, so the verb's one menu seat is
    the Step menu — the canvas right-click and toolbar reach the same id."""
    spec = services.actions.spec("order.open")
    assert (spec.menu, spec.group, spec.palette) == ("Step", "open", True)


# -- the export ------------------------------------------------------------------------------


def test_the_export_rows_carry_numbers_a_spreadsheet_can_compute_with(services, project):
    """The table renders "2w" and "18 September"; a CSV is opened to sort and sum, so it
    gets the underlying day counts and ISO dates instead."""
    from dplanner.domain.ordering import placed
    from dplanner.domain.schedule import schedule
    from dplanner.modules.step_order.export import order_rows

    order = placed(services.document, project)
    days = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    scheduled = schedule(order, lambda step: days[step.title], date(2026, 9, 7))
    milestone = project.steps[3].id
    rows = order_rows(
        scheduled, lambda _s: [], lambda step_id: "MVP" if step_id == milestone else ""
    )

    assert rows[0][:3] == ["#", "Step", "Wave"]
    assert rows[1][:5] == ["1", "A", "Ready to start", "1", "1"]
    # The milestone row: 10 accumulated days, all of them since the start (no milestone before),
    # landing on the tenth working day after the Monday start.
    assert rows[4][3:8] == ["4", "10", "10", "2026-09-18", "MVP"]
    assert rows[1][5] == ""  # A plain row does not repeat the accumulated column.


def test_file_export_writes_the_order_as_csv(services, project, tmp_path, monkeypatch):
    """File ▸ Export ▸ Order List asks for a path and writes the rows; Excel reads the BOM."""
    from PySide6.QtWidgets import QFileDialog

    from dplanner.framework.context import ContextNode, selection_uri

    for step, days in zip(project.steps, (1.0, 2.0, 3.0, 4.0), strict=True):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))

    target = tmp_path / "plan.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(target), "CSV files (*.csv)")),
    )
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("order.export", services.context.current())

    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("#,Step,Wave")
    assert lines[4].split(",")[:5] == ["4", "D", "Wave 3", "4", "10"]

    spec = services.actions.spec("order.export")
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")


# -- the CLI, with no window at all --------------------------------------------------------------


def test_the_cli_gives_the_same_answer(cli):
    """No `qapp` fixture: what an agent asks is derived on the spot and cannot be stale."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    found = json.loads(cli("order", "show", "Discovery", "--json"))["steps"]
    assert [(s["index"], s["wave"], s["title"]) for s in found] == [(1, 1, "A"), (2, 2, "B")]
    ready = json.loads(cli("order", "show", "Discovery", "--ready", "--json"))["steps"]
    assert [s["title"] for s in ready] == ["A"]

    # The window and the terminal show the same three columns.
    assert cli("order", "show", "Discovery").splitlines()[0].split() == ["#", "Step", "Wave"]


def test_a_background_table_does_not_publish_its_selection(services, project, tab):
    """One selection scope, and this table often sits beside the graph. Only the pane the
    user is in may write to it."""
    tab.on_deactivated()
    tab.table.selectRow(0)
    assert services.context.current().selected_entities("step") == []

    tab.on_activated()
    assert services.context.current().selected_entities("step") == [project.steps[0].id]
