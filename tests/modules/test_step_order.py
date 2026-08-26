"""The order view: waves and dates on screen, and the seams it reaches other features through."""

import json
from io import StringIO

import pytest
from PySide6.QtCore import QDate

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_order.view import (
    ACCUMULATED_COLUMN,
    ASPECTS_COLUMN,
    DATE_COLUMN,
    ESTIMATE_COLUMN,
)


@pytest.fixture
def project(services):
    """A → B, A → C, and D waiting on both B and C: three waves, one with two steps."""
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    for title in ("A", "B", "C", "D"):
        AddNodeCommand(project.id, Step(title=title)).redo(product)
    a, b, c, d = project.steps
    for waiter, sources in ((b, [a]), (c, [a]), (d, [b, c])):
        SetEdgesCommand(waiter.id, "requires", [s.id for s in sources]).redo(product)
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


def test_the_days_accumulate_down_the_order(services, project, tab):
    for step, days in zip(project.steps, (1.0, 2.0, 3.0, 4.0), strict=True):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))

    accumulated = [tab.table.item(row, ACCUMULATED_COLUMN).text() for row in range(4)]
    assert accumulated == ["1d", "3d", "6d", "2w"]


def test_there_is_no_date_column_until_there_is_a_start_date(services, project, tab):
    """A column of blanks says less than an absent one, and the bar above says why."""
    services.undo.push(SetModuleDataCommand(project.steps[0].id, "estimation", {"days": 3.0}))
    assert tab.table.isColumnHidden(DATE_COLUMN)

    tab.start_bar.date.setDate(QDate(2026, 9, 7))  # A Monday.
    assert not tab.table.isColumnHidden(DATE_COLUMN)
    assert tab.table.item(0, DATE_COLUMN).text() == "2026-09-09"


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


def test_activating_a_step_reveals_it_in_the_graph(services, project, tab):
    """The other seam: a callback from the composition root, so neither module imports the
    other."""
    tab.table.cellActivated.emit(0, 1)

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


# -- the CLI, with no window at all --------------------------------------------------------------


def test_the_cli_gives_the_same_answer(tmp_path):
    """No `qapp` fixture: what an agent asks is derived on the spot and cannot be stale."""
    from dplanner.core.storage.local import LocalStorage
    from dplanner.domain.seed import create_product

    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def cli(*argv):
        out = StringIO()
        code = run(registry, default_module_formats(), ["--workspace", str(root), *argv], out)
        assert code == 0, out.getvalue()
        return out.getvalue()

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
