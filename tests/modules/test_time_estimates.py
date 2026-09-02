"""The time estimates tab: the staffing picker and milestones on the left, the calendar
they date on the right."""

from datetime import date

import pytest
from PySide6.QtCore import QDate

from dplanner.domain.commands import (
    AddNodeCommand,
    EditTextCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step, TextEdit
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as write_days
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as write_milestone_label
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    PALETTE,
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
def staged(services, project):
    """The chain closed by two milestones: v1 is the model, v2 a 2d "Ship the docs" on top
    of it and the agent's docs. v1 lands 16 September; v2 begins the 17th, and the agent
    day then four calendar days of shipping land it on the 23rd."""
    library = services.document
    AddNodeCommand(project.id, Step(title="Ship the docs")).redo(library)
    _read, draft, docs, ship = project.steps
    SetEdgesCommand(ship.id, "requires", [docs.id, draft.id]).redo(library)
    SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(2.0)).redo(library)
    SetModuleDataCommand(draft.id, MILESTONE_ID, write_milestone_label("v1")).redo(library)
    SetModuleDataCommand(ship.id, MILESTONE_ID, write_milestone_label("v2")).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("time", project.id)


def _landings(tab):
    return [(row.landing.label, row.when.text(), row.days.text()) for row in tab.landings.rows]


# -- the grid and the answer -----------------------------------------------------------------


def test_the_default_team_dates_the_plan_in_the_landing_list(tab):
    assert tab.landing == date(2026, 9, 16)
    assert tab.matrix.value_at(1, 1) == "1.6w"
    assert _landings(tab) == [("All work", "16 September", "1.6w")]
    assert not tab.landings.total.isVisibleTo(tab.widget)  # one stretch needs no total
    assert not tab.notice.isVisibleTo(tab.widget)


def test_selecting_a_tile_re_asks_the_question(tab):
    tab.matrix.select(2, 3)
    assert "2 people + 3 agents" in tab.matrix.tooltip_for(
        next(cell for cell in tab._report.calendar if (cell.humans, cell.agents) == (2, 3))
    )
    assert tab.landing == date(2026, 9, 16)  # the chain does not care


def test_the_lens_toggle_swaps_the_grid_not_the_answer(tab):
    tab.project_button.click()
    assert tab.matrix.value_at(1, 1) == "4d"  # project working days now
    assert tab.landing == date(2026, 9, 16)  # the calendar keeps its dates
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


def test_clicking_a_day_re_dates_the_plan_undoably(services, project, tab):
    tab.months.day_picked.emit(date(2026, 9, 14))
    assert project.module_data[ESTIMATION_ID]["start"] == "2026-09-14"
    assert tab.months.span[0] == date(2026, 9, 14)
    tab.months.day_picked.emit(date(2026, 9, 14))  # the same day is not a second edit
    services.undo.undo()
    assert project.module_data[ESTIMATION_ID]["start"] == "2026-09-07"


def test_the_arrows_page_the_window_through_time(tab):
    assert tab.months.first_month == date(2026, 8, 1)
    tab.earlier.click()
    assert tab.months.first_month == date(2026, 7, 1)
    tab.later.click()
    tab.later.click()
    assert tab.months.first_month == date(2026, 9, 1)
    tab.matrix.select(2, 2)  # a re-render keeps the paged window
    assert tab.months.first_month == date(2026, 9, 1)


def test_the_months_light_the_work_period(tab):
    tab.months.resize(400, 100)
    assert tab.months.span == (date(2026, 9, 7), date(2026, 9, 16))
    assert tab.months.first_month == date(2026, 8, 1)  # one month before the start
    assert tab.months.month_count == 6
    assert "All work starts, working day 1 of 8" in tab.months.day_tooltip(date(2026, 9, 7))
    assert "working day 4 of 8" in tab.months.day_tooltip(date(2026, 9, 10))
    assert "weekend, not counted" in tab.months.day_tooltip(date(2026, 9, 12))
    assert "click to start the work here" in tab.months.day_tooltip(date(2026, 9, 17))


def test_the_calendar_fills_the_width_it_is_given(tab):
    tab.months.resize(700, 100)
    assert tab.months.columns == 4
    assert tab.months.cell_size == 21
    assert tab.months.month_count == 8  # six wanted, rounded up to fill two rows of four
    assert tab.months.height() > 0
    tab.months.resize(200, 100)
    assert tab.months.columns == 1
    assert tab.months.cell_size == 26
    assert tab.months.month_count == 6


def test_an_unestimated_step_is_noted(services, project, tab):
    read, _draft, _docs = project.steps
    services.undo.push(SetModuleDataCommand(read.id, ESTIMATION_ID, {}))
    assert tab.notice.isVisibleTo(tab.widget)
    assert tab.notice.text() == "1 step unestimated · counted as 0d"


# -- the two pools ---------------------------------------------------------------------------


def test_without_agent_steps_the_agent_columns_collapse(services, project, tab):
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.matrix.agent_counts == (1,)
    assert tab.matrix.header_text(1) == "any agents"
    services.undo.undo()
    assert tab.matrix.agent_counts == (1, 2, 3, 4)
    assert tab.matrix.header_text(1) == "1 agent"


def test_a_separate_instruction_moves_a_step_between_pools(services, project, tab):
    """Typing an agent instruction marks the step as agent work — prose, so the tab has to
    hear ``text_edited`` too."""
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.matrix.agent_counts == (1,)
    services.undo.push(
        EditTextCommand(TextEdit(docs.id, AGENT_ID, 0, "", "Mind the edge cases"))
    )
    assert tab.matrix.agent_counts == (1, 2, 3, 4)


# -- the focus factor ------------------------------------------------------------------------


def test_the_focus_spinbox_commits_one_undoable_float(services, project, tab):
    assert tab.focus_bar.percent.value() == 50
    tab.focus_bar.percent.setValue(25)
    entry = project.module_data[MODULE_ID]
    assert entry["efficiency"] == 0.25 and isinstance(entry["efficiency"], float)
    assert tab.matrix.value_at(1, 1) == "3.2w"
    assert tab.landing == date(2026, 9, 28)
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


# -- milestones in sequence ------------------------------------------------------------------


def test_the_milestones_land_in_sequence_and_the_total_closes_the_list(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    assert tab.milestones.keys == (draft.id, ship.id)
    assert _landings(tab) == [("v1", "16 September", "1.6w"), ("v2", "23 September", "5d")]
    assert tab.landings.total.isVisibleTo(tab.widget)
    assert tab.landings.total_when.text() == "23 September"
    assert tab.landings.total_days.text() == "2.6w"  # 13 working days, 7 → 23 September
    assert tab.landing == date(2026, 9, 23)


def test_a_stretch_prints_whole_days_never_the_simulation_fraction(services, staged):
    """At 60% focus a 2d step stretches to 3.33d; two of them land in seven working days,
    and seven is what the list says — not 6.66667."""
    tab = services.tabs.open("time", staged.id)
    tab.focus_bar.percent.setValue(60)
    assert _landings(tab)[0] == ("v1", "15 September", "7d")


def test_each_milestone_wears_its_place_in_the_palette(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    assert tab.milestones.row(draft.id).swatch.color.name() == PALETTE[0]
    assert tab.milestones.row(ship.id).swatch.color.name() == PALETTE[1]
    assert tab.milestones.row(draft.id).name.text() == "v1"
    assert tab.milestones.row(draft.id).title.text() == "Draft the model"


def test_the_calendar_paints_each_stretch_and_marks_the_landing(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    first = tab.months.band_at(date(2026, 9, 10))
    second = tab.months.band_at(date(2026, 9, 21))
    assert first is not None and first.key == draft.id and first.label == "v1"
    assert second is not None and second.key == ship.id
    assert first.color.name() == PALETTE[0] and second.color.name() == PALETTE[1]
    assert "v1 lands" in tab.months.day_tooltip(date(2026, 9, 16))
    assert "v2 starts, working day 1 of 5" in tab.months.day_tooltip(date(2026, 9, 17))
    assert "v2 lands" in tab.months.day_tooltip(date(2026, 9, 23))


def test_dating_a_milestone_starts_with_the_day_the_sequence_gave_it(services, staged):
    """*Date…* pre-fills the stretch's own start, so choosing a date is one click and an
    edit; the cross hands the decision back to the sequence. Both undo."""
    tab = services.tabs.open("time", staged.id)
    _read, _draft, _docs, ship = staged.steps
    row = tab.milestones.row(ship.id)
    assert row.set_date.isVisibleTo(tab.widget) and not row.date.isVisibleTo(tab.widget)
    row.set_date.click()
    assert ship.module_data[MODULE_ID] == {"start": "2026-09-17", "format": 1}
    assert row.date.isVisibleTo(tab.widget) and not row.set_date.isVisibleTo(tab.widget)
    row.date.setDate(QDate(2026, 10, 5))
    assert ship.module_data[MODULE_ID]["start"] == "2026-10-05"
    assert _landings(tab)[1] == ("v2", "9 October", "5d")
    assert tab.milestones.row(ship.id) is row  # the row the edit came from survives
    row.clear.click()
    assert MODULE_ID not in ship.module_data
    assert _landings(tab)[1] == ("v2", "23 September", "5d")
    services.undo.undo()  # a burst of edits to one milestone is one step, like typing
    assert MODULE_ID not in ship.module_data
    services.undo.redo()
    assert MODULE_ID not in ship.module_data


def test_a_date_the_sequence_cannot_keep_is_pushed_and_flagged(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, _draft, _docs, ship = staged.steps
    tab.milestones.row(ship.id).date.setDate(QDate(2026, 9, 10))
    tab.milestones.row(ship.id).start_changed.emit(ship.id, date(2026, 9, 10))
    v2 = tab.landings.rows[1]
    assert v2.when.text() == "⚠ 23 September"
    assert "Asked to begin 10 September" in v2.toolTip()


def test_a_chosen_colour_overrides_the_dealt_one_until_automatic(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    tab.milestones.row(draft.id).swatch.color_picked.emit("#C98500")
    assert draft.module_data[MODULE_ID] == {"color": "#c98500", "format": 1}
    assert tab.milestones.row(draft.id).swatch.color.name() == "#c98500"
    assert tab.months.band_at(date(2026, 9, 10)).color.name() == "#c98500"
    assert tab.milestones.row(ship.id).swatch.color.name() == PALETTE[1]  # still dealt in turn
    assert tab.landings.rows[0].landing.color.name() == "#c98500"
    tab.milestones.row(draft.id).swatch.color_picked.emit(None)
    assert MODULE_ID not in draft.module_data


def test_a_dated_milestone_keeps_its_colour_and_vice_versa(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, _ship = staged.steps
    tab.milestones.row(draft.id).swatch.color_picked.emit("#c98500")
    tab.milestones.row(draft.id).start_changed.emit(draft.id, date(2026, 9, 1))
    assert draft.module_data[MODULE_ID] == {
        "start": "2026-09-01",
        "color": "#c98500",
        "format": 1,
    }
    tab.milestones.row(draft.id).swatch.color_picked.emit(None)
    assert draft.module_data[MODULE_ID] == {"start": "2026-09-01", "format": 1}


def test_picking_a_milestone_emphasises_its_stretch_on_both_sides(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    tab.milestones.row(ship.id).picked.emit(ship.id)
    assert tab.picked == ship.id
    assert tab.months.emphasised == ship.id
    assert tab.landings.rows[1].selected and not tab.landings.rows[0].selected
    assert tab.milestones.row(ship.id).selected
    tab.landings.rows[1].picked.emit(ship.id)  # picked again, from the other list: let go
    assert tab.picked is None and tab.months.emphasised is None
    tab.landings.rows[0].picked.emit(draft.id)
    services.undo.push(SetModuleDataCommand(draft.id, MILESTONE_ID, {}))  # no longer one
    assert tab.picked is None


def test_removing_a_milestone_step_takes_its_row_with_it(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    services.undo.push(RemoveNodeCommand(ship.id))
    assert tab.milestones.keys == (draft.id,)
    assert [label for label, _when, _days in _landings(tab)] == ["v1", "Remaining work"]


def test_without_milestones_the_list_says_where_to_make_one(tab):
    assert tab.milestones.empty.isVisibleTo(tab.widget)
    assert "Step ▸ Type ▸ Milestone" in tab.milestones.empty.text()


# -- what breaks, said plainly ---------------------------------------------------------------


def test_a_loop_in_the_file_says_which_steps_wait_on_each_other(services, project, tab):
    """The model refuses a cycle; a file does not. Write one behind its back."""
    library = services.document
    read, draft, _docs = project.steps
    read.edges["requires"] = [draft.id]
    library.edges_changed.emit(read.id, None)
    assert not tab.months.isVisibleTo(tab.widget)
    assert not tab.matrix.isVisibleTo(tab.widget)
    assert tab.notice.isVisibleTo(tab.widget)
    assert "Read the spec, Draft the model" in tab.notice.text()
    assert "Unlink one" in tab.notice.text()
    read.edges["requires"] = []
    library.edges_changed.emit(read.id, None)
    assert tab.months.isVisibleTo(tab.widget)
    assert tab.landing == date(2026, 9, 16)


def test_a_stepless_project_says_so_instead_of_a_grid_of_zeros(services, make_project):
    empty = make_project("Empty")
    tab = services.tabs.open("time", empty.id)
    assert tab.notice.text() == "No steps yet"
    assert not tab.matrix.isVisibleTo(tab.widget)
    assert not tab.lens_bar.isVisibleTo(tab.widget)
    assert not tab.months.isVisibleTo(tab.widget)


def test_the_tab_titles_itself_after_the_project(tab):
    assert tab.title == "Discovery — Time Estimates"
