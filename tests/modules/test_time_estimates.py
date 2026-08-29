"""The time estimates tab: the staffing matrices on screen, and the one stored assumption."""

from datetime import date

import pytest

from dplanner.domain.commands import (
    AddNodeCommand,
    EditTextCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step, TextEdit
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as write_days
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    read_efficiency,
    stretched,
)
from dplanner.modules.time_estimates.view import LABEL_COLUMN, SECONDARY_ALPHA


@pytest.fixture
def project(services, make_project):
    """Two 2d human steps in a chain, one independent 1d agent step, dated.

    Human work serialises to 4d whatever the staffing, so every parallel cell reads 4d
    and — at the default 50% focus — every calendar cell reads 8d, landing eight working
    days after Monday 7 September 2026.
    """
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Draft the model", "Write the docs"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    read, draft, docs = project.steps
    SetEdgesCommand(draft.id, "requires", [read.id]).redo(library)
    for step, days in ((read, 2.0), (draft, 2.0), (docs, 1.0)):
        SetModuleDataCommand(step.id, ESTIMATION_ID, write_days(days)).redo(library)
    SetModuleDataCommand(docs.id, AGENT_ID, write_state(True)).redo(library)
    SetModuleDataCommand(
        project.id, ESTIMATION_ID, write_start(date(2026, 9, 7))
    ).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("time", project.id)


def column_of(agents: int) -> int:
    return LABEL_COLUMN + agents


# -- what it shows ---------------------------------------------------------------------------


def test_both_matrices_price_the_scenario(tab):
    assert tab.parallel.item(0, column_of(1)).text() == "4d"
    assert tab.parallel.item(2, column_of(4)).text() == "4d"
    assert tab.calendar.item(0, column_of(1)).text() == "1.6w · 16 September"
    assert tab.parallel.item(0, LABEL_COLUMN).text() == "1 human"
    assert "4d human, 1d agent" in tab.summary.text()
    assert not tab.unestimated_note.isVisibleTo(tab.widget)
    assert not tab.agent_note.isVisibleTo(tab.widget)


def test_the_matrix_follows_the_graph(services, project, tab):
    """Nothing is stored: unlinking the chain halves the makespan with two humans."""
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    assert tab.parallel.item(0, column_of(1)).text() == "4d"  # one human still serialises
    assert tab.parallel.item(1, column_of(1)).text() == "2d"
    services.undo.undo()
    assert tab.parallel.item(1, column_of(1)).text() == "4d"


def test_cells_on_the_dependency_floor_fade(services, project, tab):
    """With the chain broken, one human is above the 2d floor and two humans sit on it."""
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    working = tab.parallel.item(0, column_of(1))
    floored = tab.parallel.item(1, column_of(1))
    assert working.foreground().color().alpha() == 255
    assert floored.foreground().color().alpha() == SECONDARY_ALPHA


def test_an_unestimated_step_is_flagged(services, project, tab):
    read, _draft, _docs = project.steps
    services.undo.push(SetModuleDataCommand(read.id, ESTIMATION_ID, {}))
    assert tab.unestimated_note.isVisibleTo(tab.widget)
    assert "1 step unestimated" in tab.unestimated_note.text()


# -- the two pools ---------------------------------------------------------------------------


def test_without_agent_steps_the_agent_columns_collapse(services, project, tab):
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.parallel.isColumnHidden(column_of(2))
    assert tab.parallel.horizontalHeaderItem(column_of(1)).text() == "any agents"
    assert tab.agent_note.isVisibleTo(tab.widget)

    services.undo.undo()
    assert not tab.parallel.isColumnHidden(column_of(2))
    assert tab.parallel.horizontalHeaderItem(column_of(1)).text() == "1 agent"


def test_a_separate_instruction_moves_a_step_between_pools(services, project, tab):
    """Typing an agent instruction marks the step as agent work — prose, so the tab has to
    hear ``text_edited`` too."""
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.agent_note.isVisibleTo(tab.widget)
    services.undo.push(
        EditTextCommand(TextEdit(docs.id, AGENT_ID, 0, "", "Mind the edge cases"))
    )
    assert not tab.agent_note.isVisibleTo(tab.widget)


# -- the focus factor ------------------------------------------------------------------------


def test_the_focus_spinbox_commits_one_undoable_float(services, project, tab):
    assert tab.focus_bar.percent.value() == 50
    tab.focus_bar.percent.setValue(25)
    entry = project.module_data[MODULE_ID]
    assert entry["efficiency"] == 0.25 and isinstance(entry["efficiency"], float)
    assert tab.calendar.item(0, column_of(1)).text() == "3.2w · 28 September"
    services.undo.undo()
    assert MODULE_ID not in project.module_data
    assert tab.focus_bar.percent.value() == 50  # the bar reloads off its own echo's undo


def test_a_foreign_focus_write_refreshes_bar_and_cells(services, project, tab):
    services.undo.push(
        SetModuleDataCommand(project.id, MODULE_ID, {"efficiency": 0.8, "format": 1})
    )
    assert tab.focus_bar.percent.value() == 80
    assert tab.calendar.item(0, column_of(1)).text().startswith("5d")


def test_unreadable_focus_reads_as_the_default(services, project):
    library = services.document
    for stored in (True, "half", 0.0, 1.5):
        SetModuleDataCommand(
            project.id, MODULE_ID, {"efficiency": stored, "format": 1}
        ).redo(library)
        assert read_efficiency(project) == 0.5
    SetModuleDataCommand(project.id, MODULE_ID, {"efficiency": 1, "format": 1}).redo(library)
    assert read_efficiency(project) == 1.0  # an int is a number; a bool is not


def test_stretching_prices_human_steps_only(project):
    read, _draft, docs = project.steps
    calendar_days = stretched(
        lambda step: {"Read the spec": 2.0, "Write the docs": 1.0}.get(step.title),
        lambda step: step.title == "Write the docs",
        0.5,
    )
    assert calendar_days(read) == 4.0
    assert calendar_days(docs) == 1.0


# -- the empty state -------------------------------------------------------------------------


def test_a_stepless_project_says_so_instead_of_a_grid_of_zeros(services, make_project):
    empty = make_project("Empty")
    tab = services.tabs.open("time", empty.id)
    assert "No steps yet" in tab.summary.text()
    assert not tab.parallel.isVisibleTo(tab.widget)
    assert not tab.calendar.isVisibleTo(tab.widget)


def test_the_tab_titles_itself_after_the_project(tab):
    assert tab.title == "Discovery — Time Estimates"
