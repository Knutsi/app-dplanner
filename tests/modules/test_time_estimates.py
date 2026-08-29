"""The time estimates tab: the headline, the heatmap, and the one stored assumption."""

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
from dplanner.modules.time_estimates.view import TINT_MIN_ALPHA


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


# -- the headline and the grid ---------------------------------------------------------------


def test_the_headline_answers_for_the_default_team(tab):
    assert tab.headline.text() == "Lands 16 September"
    assert "1 person + 1 agent" in tab.detail.text()
    assert "1.6w of calendar time" in tab.detail.text()
    assert tab.matrix.value_at(1, 1) == "1.6w"
    assert not tab.unestimated_note.isVisibleTo(tab.widget)
    assert not tab.agent_note.isVisibleTo(tab.widget)


def test_selecting_a_tile_re_asks_the_question(tab):
    tab.matrix.select(2, 3)
    assert "2 people + 3 agents" in tab.detail.text()
    assert tab.headline.text() == "Lands 16 September"  # the chain does not care


def test_the_lens_toggle_swaps_the_grid_not_the_answer(tab):
    tab.project_button.click()
    assert tab.matrix.value_at(1, 1) == "4d"  # project working days now
    assert "1.6w of calendar time" in tab.detail.text()  # the headline strip keeps both
    tab.calendar_button.click()
    assert tab.matrix.value_at(1, 1) == "1.6w"


def test_the_matrix_follows_the_graph(services, project, tab):
    """Nothing is stored: unlinking the chain halves the makespan with two humans."""
    tab.project_button.click()
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    assert tab.matrix.value_at(1, 1) == "4d"  # one human still serialises
    assert tab.matrix.value_at(2, 1) == "2d"
    services.undo.undo()
    assert tab.matrix.value_at(2, 1) == "4d"


def test_more_time_wears_more_ink_and_the_floor_is_lightest(services, project, tab):
    """With the chain broken, one human sits above the 2d floor and two humans on it."""
    tab.project_button.click()
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    assert tab.matrix.tint_alpha(1, 1) > tab.matrix.tint_alpha(2, 1)
    assert tab.matrix.tint_alpha(2, 1) == TINT_MIN_ALPHA


def test_the_insight_names_the_smallest_team_on_the_floor(services, project, tab):
    assert "Staffing does not change this plan" in tab.insight.text()
    tab.project_button.click()
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    assert "2 people + 1 agent" in tab.insight.text()
    assert "dependency floor" in tab.insight.text()


def test_the_months_light_the_work_period(tab):
    assert tab.months.span == (date(2026, 9, 7), date(2026, 9, 16))
    assert tab.months.first_month == date(2026, 8, 1)  # one month before the start
    assert tab.months.month_count == 6
    assert "the work starts" in tab.months.day_tooltip(date(2026, 9, 7))
    assert "working day 4 of 8" in tab.months.day_tooltip(date(2026, 9, 10))
    assert "weekend, not counted" in tab.months.day_tooltip(date(2026, 9, 12))
    assert "the work lands" in tab.months.day_tooltip(date(2026, 9, 16))


def test_an_unestimated_step_is_flagged(services, project, tab):
    read, _draft, _docs = project.steps
    services.undo.push(SetModuleDataCommand(read.id, ESTIMATION_ID, {}))
    assert tab.unestimated_note.isVisibleTo(tab.widget)
    assert "1 step unestimated" in tab.unestimated_note.text()


# -- the two pools ---------------------------------------------------------------------------


def test_without_agent_steps_the_agent_columns_collapse(services, project, tab):
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.matrix.agent_counts == (1,)
    assert tab.matrix.header_text(1) == "any agents"
    assert tab.agent_note.isVisibleTo(tab.widget)

    services.undo.undo()
    assert tab.matrix.agent_counts == (1, 2, 3, 4)
    assert tab.matrix.header_text(1) == "1 agent"


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
    assert tab.matrix.value_at(1, 1) == "3.2w"
    assert tab.headline.text() == "Lands 28 September"
    services.undo.undo()
    assert MODULE_ID not in project.module_data
    assert tab.focus_bar.percent.value() == 50  # the bar reloads off its own echo's undo


def test_a_foreign_focus_write_refreshes_bar_and_cells(services, project, tab):
    services.undo.push(
        SetModuleDataCommand(project.id, MODULE_ID, {"efficiency": 0.8, "format": 1})
    )
    assert tab.focus_bar.percent.value() == 80
    assert tab.matrix.value_at(1, 1) == "5d"


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
    assert tab.headline.text() == "No steps yet"
    assert not tab.matrix.isVisibleTo(tab.widget)
    assert not tab.lens_bar.isVisibleTo(tab.widget)


def test_the_tab_titles_itself_after_the_project(tab):
    assert tab.title == "Discovery — Time Estimates"
