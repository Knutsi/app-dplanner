"""The Estimates tab: many steps sized in one sitting, opened from a selection.

What matters here is the seams: the action reads the same selection scope every verb reads,
the rows write through the same command the detail panel writes, and the tab lands beside
the canvas without either module knowing the other's name.
"""

import pytest
from PySide6.QtWidgets import QDoubleSpinBox

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, activity_uri, selection_uri
from dplanner.framework.list_rows import VALUE_ROLE
from dplanner.modules.estimation.aspect import read as read_estimate
from dplanner.modules.estimation.bulk import (
    ESTIMATE_COLUMN,
    ESTIMATE_KIND,
    NONE_SIZED,
    BulkEstimateActivity,
)


@pytest.fixture
def project(services, make_project):
    """A → B, A → C, and D waiting on both B and C: a known topological order."""
    library = services.document
    project = make_project("Discovery")
    for title in ("A", "B", "C", "D"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    a, b, c, d = project.steps
    for waiter, sources in ((b, [a]), (c, [a]), (d, [b, c])):
        SetEdgesCommand(waiter.id, "requires", [s.id for s in sources]).redo(library)
    return project


def select(services, *steps):
    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", step.id)) for step in steps)
    )


def run_estimate_open(services):
    services.actions.run("estimate.open", services.context.current())


def estimate_tab(services):
    found = [a for a in services.tabs.activities() if isinstance(a, BulkEstimateActivity)]
    assert len(found) <= 1
    return found[0] if found else None


def editor_at(tab, row):
    """The estimate's editor on ``row``, opened if it is not already."""
    index = tab.table.model().index(row, ESTIMATE_COLUMN)
    tab.table.setCurrentCell(row, ESTIMATE_COLUMN)
    if tab.table.indexWidget(index) is None:
        tab.table.edit(index)
    box = tab.table.indexWidget(index)
    assert isinstance(box, QDoubleSpinBox)
    return box


def titles_on_screen(tab):
    return [
        tab.table.item(row, 0).text()
        for row in range(tab.table.rowCount())
        if not tab.table.isRowHidden(row)
    ]


# -- opening -------------------------------------------------------------------------------


def test_the_action_opens_a_tab_scoped_to_the_selection(services, project):
    b, c = project.steps[1], project.steps[2]
    select(services, b, c)
    run_estimate_open(services)

    tab = estimate_tab(services)
    assert tab is not None
    assert tab.uri == activity_uri(ESTIMATE_KIND, project.id)
    assert titles_on_screen(tab) == ["B", "C"]
    assert tab.controls.is_shown(tab.scope_box)
    assert tab.scope_box.itemText(0) == "Selection (2)"
    assert tab.scope_box.currentData() == "selection"


def test_the_action_reads_the_whole_project_when_nothing_is_selected(services, project):
    services.tabs.open("project", project.id)  # The menu-bar path: a project in focus.
    run_estimate_open(services)

    tab = estimate_tab(services)
    assert tab is not None
    assert titles_on_screen(tab) == ["A", "B", "C", "D"]  # placed() order.
    assert not tab.controls.is_shown(tab.scope_box)  # One entry would teach nothing.


def test_the_action_names_the_count_it_will_estimate(services, project):
    select(services, *project.steps[:3])
    state = services.actions.spec("estimate.open").state(services.context.current())
    assert state.label == "&Estimate 3 Steps"


def test_the_action_greys_off_any_project(services):
    state = services.actions.spec("estimate.open").state(services.context.current())
    assert state.visible and not state.enabled


def test_the_tab_opens_beside_the_canvas(services, project):
    services.tabs.open("project", project.id)
    select(services, project.steps[0])
    run_estimate_open(services)

    assert services.tabs.group_count() == 2
    assert services.tabs.current_activity() is estimate_tab(services)


def test_reinvoking_rescopes_the_same_tab_where_it_is(services, project):
    services.tabs.open("project", project.id)
    select(services, project.steps[0], project.steps[1])
    run_estimate_open(services)
    groups = services.tabs.group_count()

    select(services, project.steps[3])
    run_estimate_open(services)

    tab = estimate_tab(services)
    assert titles_on_screen(tab) == ["D"]
    assert tab.scope_box.itemText(0) == "Selection (1)"
    assert services.tabs.group_count() == groups


def test_the_scope_can_widen_to_the_whole_project(services, project):
    select(services, project.steps[3])
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab.scope_box.setCurrentIndex(1)  # Whole project.
    assert titles_on_screen(tab) == ["A", "B", "C", "D"]
    tab.scope_box.setCurrentIndex(0)  # Back to the selection.
    assert titles_on_screen(tab) == ["D"]


# -- what a row shows ----------------------------------------------------------------------


def test_a_row_shows_title_and_first_description_line(services, project):
    a = project.steps[0]
    services.document.set_text(
        a.id, "step_description", "# A\nSkim the spec before anything else.\nMore prose."
    )
    select(services, a)
    run_estimate_open(services)

    tab = estimate_tab(services)
    description = tab.table.item(0, 2)
    assert description.text() == "Skim the spec before anything else."
    assert "More prose." in description.toolTip()


def test_a_description_written_later_reaches_the_row(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.document.set_text(project.steps[0].id, "step_description", "Now described.")
    assert tab.table.item(0, 2).text() == "Now described."


def test_a_rename_reaches_the_row(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(SetFieldCommand(project.steps[0].id, "title", "A, renamed"))
    assert tab.table.item(0, 0).text() == "A, renamed"


# -- writing estimates ---------------------------------------------------------------------


def test_a_number_typed_in_the_cell_writes_an_undoable_estimate(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    box = editor_at(tab, 0)
    box.setValue(0.5)
    tab.table.commitData(box)
    assert read_estimate(services.document.step(a.id)) == 0.5
    assert tab.table.item(0, ESTIMATE_COLUMN).text() == "0.5 d"

    services.undo.undo()
    assert read_estimate(services.document.step(a.id)) is None
    assert tab.table.item(0, ESTIMATE_COLUMN).data(VALUE_ROLE) is None  # The undo reached it.
    assert tab.table.item(0, ESTIMATE_COLUMN).text() == "—"


def test_sizing_several_picked_rows_from_the_strip_is_one_undo_step(services, project):
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)
    tab.table.selectAll()

    state = services.actions.spec("estimate.size_2").state(services.context.current())
    assert state.enabled and state.label == "½ Day for 4 Steps"
    services.actions.run("estimate.size_2", services.context.current())
    assert [read_estimate(services.document.step(s.id)) for s in project.steps] == [0.5] * 4
    assert [tab.table.item(row, ESTIMATE_COLUMN).text() for row in range(4)] == ["0.5 d"] * 4
    services.undo.undo()
    assert all(read_estimate(services.document.step(s.id)) is None for s in project.steps)


def test_a_size_verb_is_greyed_with_its_reason_until_a_step_is_picked(services, project):
    services.context.set_scope(SCOPE_SELECTION, ())
    state = services.actions.spec("estimate.size_4").state(services.context.current())
    assert state.visible and not state.enabled and state.label == "1 Day — pick a step"


def test_a_change_made_elsewhere_reaches_the_row(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    assert tab.table.item(0, ESTIMATE_COLUMN).data(VALUE_ROLE) == 3.0
    assert tab.table.item(0, ESTIMATE_COLUMN).text() == "3 d"


def test_the_tables_own_write_is_not_echoed_back_over_typing(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    box = editor_at(tab, 0)
    box.setValue(2.0)
    tab.table.commitData(box)
    box.setValue(7.0)  # Typed, not yet committed.
    services.document.set_module_data(a.id, "estimation", {"days": 2.0, "format": 1}, tab.table)
    assert box.value() == 7.0


# -- filters and the summary ---------------------------------------------------------------


def test_the_unestimated_filter_hides_what_is_sized(services, project):
    """The run-down-the-list mode — and the regression test for rebuilding inside a chip's
    own click, which is why sizing a row may only hide it, never delete it."""
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)
    tab.set_filter("unestimated")

    box = editor_at(tab, 0)
    box.setValue(1.0)
    tab.table.commitData(box)  # From the row itself, inside the editor's own commit.
    assert titles_on_screen(tab) == ["B", "C", "D"]
    assert tab.table.isRowHidden(0)


def test_the_estimated_filter_is_the_review_mode(services, project):
    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab.filter_box.setCurrentIndex(tab.filter_box.findData("estimated"))
    assert titles_on_screen(tab) == ["A"]


def test_the_summary_counts_and_totals_over_the_scope(services, project):
    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)

    # The volume sentence the order table and ``estimate rollup`` print, over this scope.
    assert tab.volume.text() == "3 days over 4 steps, 3 unestimated"
    tab.filter_box.setCurrentIndex(tab.filter_box.findData("unestimated"))
    assert tab.volume.text() == "3 days over 4 steps, 3 unestimated"  # Hiding rows adds nothing.


def test_a_filter_that_leaves_nothing_says_what_it_is_waiting_for(services, project):
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)
    tab.filter_box.setCurrentIndex(tab.filter_box.findData("estimated"))
    assert tab.empty.isVisibleTo(tab.widget) and tab.empty.text() == NONE_SIZED
    assert not tab.table.isVisibleTo(tab.widget)


# -- the model moving under the tab --------------------------------------------------------


def test_a_deleted_step_leaves_the_scope(services, project):
    a, b = project.steps[0], project.steps[1]
    select(services, a, b)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(RemoveNodeCommand(b.id))
    assert titles_on_screen(tab) == ["A"]
    assert tab.scope_box.itemText(0) == "Selection (1)"


def test_an_emptied_scope_falls_back_to_the_whole_project(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(RemoveNodeCommand(a.id))
    assert not tab.controls.is_shown(tab.scope_box)
    assert titles_on_screen(tab) == ["B", "C", "D"]


def test_a_deleted_project_takes_the_tab_with_it(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    assert estimate_tab(services) is not None

    services.undo.push(RemoveNodeCommand(project.id))
    assert estimate_tab(services) is None


def test_the_tab_retitles_on_project_rename(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(SetFieldCommand(project.id, "title", "Delivery"))
    assert services.tabs.tab_title(tab) == "Delivery — Estimates"


# -- speaking for the user -----------------------------------------------------------------


def test_selecting_a_row_publishes_the_step(services, project):
    select(services, project.steps[0], project.steps[1])
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab.table.selectRow(1)
    selected = services.context.current().selected_entities("step")
    assert selected == [project.steps[1].id]


def test_a_background_tab_does_not_publish(services, project):
    select(services, project.steps[0], project.steps[1])
    run_estimate_open(services)
    tab = estimate_tab(services)
    tab.table.selectRow(0)

    tab.on_deactivated()
    services.context.set_scope(SCOPE_SELECTION, ())
    tab.table.selectRow(1)
    assert services.context.current().selected_entities("step") == []


def test_activating_a_row_opens_its_details(services, project, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    b = project.steps[1]
    select(services, b)
    run_estimate_open(services)
    tab = estimate_tab(services)

    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    tab.table.cellActivated.emit(0, 0)
    assert shown == [b.id]
