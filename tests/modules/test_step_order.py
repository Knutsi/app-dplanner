"""The order view: waves and volume on screen, and the seams it reaches other features through."""

import json
from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.framework.list_rows import EMPHASIS_ROLE, TINT_ROLE
from dplanner.framework.table import row_height
from dplanner.modules.step_order.view import (
    ASPECTS_COLUMN,
    ESTIMATE_COLUMN,
    MILESTONE_ROLE,
    TITLE_COLUMN,
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
        ("1", "A", "Wave 1"),
        ("2", "B", "Wave 2"),
        ("3", "C", "Wave 2"),
        ("4", "D", "Wave 3"),
    ]


def test_the_table_follows_the_graph(services, project, tab):
    """Nothing is stored, so a new edge renumbers the table with no recompute to remember."""
    _a, b, _c, _d = project.steps
    services.undo.push(SetEdgesCommand(b.id, "requires", []))
    assert rows_on_screen(tab)[:2] == [
        ("1", "A", "Wave 1"),
        ("2", "B", "Wave 1"),
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
    # The one weight in the table — DESIGN.md's Tables: a milestone is a fixed point, found
    # by a glance down the column. The weight is the delegate's, so it is read off the role
    # the primitive paints from rather than off a font set on the item.
    assert table.item(release_row, TITLE_COLUMN).data(EMPHASIS_ROLE)
    assert not table.item(0, TITLE_COLUMN).data(EMPHASIS_ROLE)
    assert "MVP" in table.item(release_row, ASPECTS_COLUMN).text()
    # Its key as a badge in the glyph slot and a wash under the row — the marks the table
    # primitive gives a fixed point. The rule that used to close the block went with the
    # hand-rolled delegate: three marks say it, and a fourth was a fourth thing to learn.
    assert not table.item(release_row, TITLE_COLUMN).icon().isNull()
    assert table.item(release_row, TITLE_COLUMN).data(TINT_ROLE) is not None
    assert table.item(0, TITLE_COLUMN).data(TINT_ROLE) is None


def test_the_page_states_the_volume_and_not_a_calendar(services, project, tab):
    """What the order can honestly say about time: how much work, over how many steps.

    The serial dates it used to run out — a step a day after the one before, from a start
    date set on this page — were never how the work happens; the Time tab simulates two
    pools of workers, and this line is the one number that holds whoever does it.
    """
    for step, days in zip(project.steps[:3], (1.0, 2.0, 3.0), strict=True):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))

    assert tab.volume.text() == "6 days over 4 steps, 1 unestimated"
    assert [column.title for column in tab.table.columns()] == ["#", "Step", "Wave", "Estimate", ""]


def test_a_project_with_no_steps_swaps_the_table_for_what_would_be_there(services, make_project):
    empty = make_project("Fresh")
    tab = services.tabs.open("order", empty.id)

    assert not tab.table.isVisible() and tab.empty.isVisible()
    assert not tab.volume.isVisible()
    AddNodeCommand(empty.id, Step(title="A")).redo(services.document)
    assert tab.table.isVisible() and not tab.empty.isVisible()


def test_every_row_is_one_height_and_it_comes_from_the_font(services, project, tab):
    """DESIGN.md's *Tables*: a fixed pixel height clips at twelve points, and a milestone
    is marked by what it wears rather than by the room around it."""
    from dplanner.modules.step_milestone.aspect import write

    services.undo.push(SetModuleDataCommand(project.steps[3].id, "step_milestone", write("MVP")))

    expected = row_height(tab.table.font(), rich=False)
    assert tab.table.verticalHeader().defaultSectionSize() == expected
    assert {tab.table.rowHeight(row) for row in range(4)} == {expected}


def test_column_headers_read_from_the_left(services, project, tab):
    """DESIGN.md's Tables: headers are left-aligned, not Qt's centred default."""
    from PySide6.QtCore import Qt

    assert tab.table.horizontalHeader().defaultAlignment() & Qt.AlignmentFlag.AlignLeft


@pytest.fixture
def mixed(services, project):
    """A a plain step, B a feature, C an agent step, D the milestone they land in."""
    from dplanner.domain.commands import EditTextCommand
    from dplanner.domain.model import TextEdit
    from dplanner.modules.feature.aspect import write as write_feature
    from dplanner.modules.step_milestone.aspect import write

    _a, b, c, d = project.steps
    services.undo.push(SetModuleDataCommand(b.id, "feature", write_feature("f1")))
    services.undo.push(EditTextCommand(TextEdit(c.id, "step_agent_instruction", 0, "", "Do it.")))
    services.undo.push(SetModuleDataCommand(d.id, "step_milestone", write("MVP")))
    return project


def test_every_row_wears_the_glyph_of_what_it_is(services, mixed, tab):
    """The canvas medallions' vocabulary, read off the same wiring: a milestone wears the
    tag, a feature the layer stack, and a work step — agent or not — the card, so steps and
    features tell apart at a glance."""
    from dplanner.modules.step_order.view import KIND_FEATURE, KIND_MILESTONE, KIND_STEP

    table = tab.table
    assert [table.kind_at(row) for row in range(4)] == [
        KIND_STEP,
        KIND_FEATURE,
        KIND_STEP,
        KIND_MILESTONE,
    ]
    assert all(not table.item(row, TITLE_COLUMN).icon().isNull() for row in range(4))
    images = [table.item(row, TITLE_COLUMN).icon().pixmap(16).toImage() for row in range(4)]
    assert images[0] == images[2]  # both work steps
    assert images[0] != images[1] != images[3]


def test_the_switches_narrow_the_order_to_steps_or_features_and_keep_the_milestones(
    services, mixed, tab
):
    """Two perspectives on one order: rows hide rather than leave, so the numbering and
    the accumulated days still read as the whole — and a milestone is never hidden."""

    def shown():
        return [tab.table.item(row, 1).text() for row in range(4) if not tab.table.isRowHidden(row)]

    assert shown() == ["A", "B", "C", "D"]
    tab.show_steps.setChecked(False)
    assert shown() == ["B", "D"]
    tab.show_features.setChecked(False)
    assert shown() == ["D"]
    tab.show_steps.setChecked(True)
    assert shown() == ["A", "C", "D"]
    assert [tab.table.item(row, 0).text() for row in range(4)] == ["1", "2", "3", "4"]
    # A rebuild keeps the perspective.
    services.undo.push(SetEdgesCommand(mixed.steps[2].id, "requires", []))
    assert shown() == ["A", "C", "D"]


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
    assert rows[1][:5] == ["1", "A", "Wave 1", "1", "1"]
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

    # The window and the terminal show the same three columns, and state the same volume.
    printed = cli("order", "show", "Discovery")
    assert printed.splitlines()[0].split() == ["#", "Step", "Wave"]
    assert printed.splitlines()[-1] == "0 days over 2 steps, 2 unestimated"

    cli("estimate", "set", "A", "--days", "1.5")
    volume = json.loads(cli("order", "show", "Discovery", "--json"))
    assert (volume["days"], volume["unestimated"]) == (1.5, 1)
    assert cli("order", "show", "Discovery").splitlines()[-1] == (
        "1.5 days over 2 steps, 1 unestimated"
    )


def test_a_background_table_does_not_publish_its_selection(services, project, tab):
    """One selection scope, and this table often sits beside the graph. Only the pane the
    user is in may write to it."""
    tab.on_deactivated()
    tab.table.selectRow(0)
    assert services.context.current().selected_entities("step") == []

    tab.on_activated()
    assert services.context.current().selected_entities("step") == [project.steps[0].id]
