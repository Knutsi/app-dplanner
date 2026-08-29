"""The Estimates tab: many steps sized in one sitting, opened from a selection.

What matters here is the seams: the action reads the same selection scope every verb reads,
the rows write through the same command the detail panel writes, and the tab lands beside
the canvas without either module knowing the other's name.
"""

import pytest

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, activity_uri, selection_uri
from dplanner.modules.estimation.aspect import read as read_estimate
from dplanner.modules.estimation.bulk import ESTIMATE_KIND, BulkEstimateActivity


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
    assert not tab._scope_bar.isHidden()
    assert tab._selection_button.text() == "Selection (2)"
    assert tab._selection_button.isChecked()


def test_the_action_reads_the_whole_project_when_nothing_is_selected(services, project):
    services.tabs.open("project", project.id)  # The menu-bar path: a project in focus.
    run_estimate_open(services)

    tab = estimate_tab(services)
    assert tab is not None
    assert titles_on_screen(tab) == ["A", "B", "C", "D"]  # placed() order.
    assert tab._scope_bar.isHidden()


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
    assert tab._selection_button.text() == "Selection (1)"
    assert services.tabs.group_count() == groups


def test_the_scope_can_widen_to_the_whole_project(services, project):
    select(services, project.steps[3])
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab._whole_button.click()
    assert titles_on_screen(tab) == ["A", "B", "C", "D"]
    tab._selection_button.click()
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
    description = tab.table.item(0, 1)
    assert description.text() == "Skim the spec before anything else."
    assert "More prose." in description.toolTip()


def test_a_description_written_later_reaches_the_row(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.document.set_text(project.steps[0].id, "step_description", "Now described.")
    assert tab.table.item(0, 1).text() == "Now described."


def test_a_rename_reaches_the_row(services, project):
    select(services, project.steps[0])
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(SetFieldCommand(project.steps[0].id, "title", "A, renamed"))
    assert tab.table.item(0, 0).text() == "A, renamed"


# -- writing estimates ---------------------------------------------------------------------


def test_a_chip_click_writes_an_undoable_estimate(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab._editors[a.id].chips.button(2).click()  # ½ a day — ids count quarter-days.
    assert read_estimate(services.document.step(a.id)) == 0.5

    services.undo.undo()
    assert read_estimate(services.document.step(a.id)) is None
    assert tab._editors[a.id].days.value() == 0.0  # The undo reached the row.


def test_a_change_made_elsewhere_reaches_the_row(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    assert tab._editors[a.id].days.value() == 3.0


def test_a_rows_own_write_is_not_echoed_back(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    editor = estimate_tab(services)._editors[a.id]

    editor.days.setValue(2.0)
    editor.days.editingFinished.emit()
    editor.days.setValue(7.0)  # Typed, not yet committed.
    services.document.set_module_data(a.id, "estimation", {"days": 2.0, "format": 1}, editor)
    assert editor.days.value() == 7.0


# -- filters and the summary ---------------------------------------------------------------


def test_the_unestimated_filter_hides_what_is_sized(services, project):
    """The run-down-the-list mode — and the regression test for rebuilding inside a chip's
    own click, which is why sizing a row may only hide it, never delete it."""
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)
    tab._filters.button(1).click()  # Unestimated.

    tab._editors[project.steps[0].id].chips.button(4).click()  # 1 day, from the row itself.
    assert titles_on_screen(tab) == ["B", "C", "D"]
    assert tab.table.isRowHidden(0)


def test_the_estimated_filter_is_the_review_mode(services, project):
    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)

    tab._filters.button(2).click()  # Estimated.
    assert titles_on_screen(tab) == ["A"]


def test_the_summary_counts_and_totals_over_the_scope(services, project):
    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "estimation", {"days": 3.0, "format": 1}))
    select(services, *project.steps)
    run_estimate_open(services)
    tab = estimate_tab(services)

    assert tab._summary.text() == "1 of 4 estimated · 3d"
    tab._filters.button(1).click()  # Hiding rows must not change the arithmetic.
    assert tab._summary.text() == "1 of 4 estimated · 3d"


# -- the model moving under the tab --------------------------------------------------------


def test_a_deleted_step_leaves_the_scope(services, project):
    a, b = project.steps[0], project.steps[1]
    select(services, a, b)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(RemoveNodeCommand(b.id))
    assert titles_on_screen(tab) == ["A"]
    assert tab._selection_button.text() == "Selection (1)"


def test_an_emptied_scope_falls_back_to_the_whole_project(services, project):
    a = project.steps[0]
    select(services, a)
    run_estimate_open(services)
    tab = estimate_tab(services)

    services.undo.push(RemoveNodeCommand(a.id))
    assert tab._scope_bar.isHidden()
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
