"""The Time tab: four figures — where the plan lands, how that moved, how much is done, what
nobody has sized — a strip holding the pages, what the plan is compared with, the Budget,
*Save Snapshot…*, ⋯ and Export, and a page at a time: the milestones against the plan
compared with, the work, the calendar. A milestone's own start and colour are set on its
Details tab."""

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
from dplanner.domain.schedule import format_date
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as write_days
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as write_milestone_label
from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
from dplanner.modules.step_status.aspect import write as write_status
from dplanner.modules.time_estimates.activity import NO_STEPS
from dplanner.modules.time_estimates.progress import (
    HISTORY_ID,
    Landing,
    Pick,
    Snapshot,
    Stretch,
    Tally,
    read_history,
    read_saved,
    write_history,
)
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    read_efficiency,
    read_palette,
    stretched,
)
from dplanner.modules.time_estimates.section import MilestoneScheduleSection
from dplanner.theme.palettes import PALETTES, shades

# The day every test here is run on, so no date the tab prints depends on the day the suite
# runs: the Friday before the plan starts, when nothing is due yet and the plan's own dates
# stand — a plan whose days have passed with nothing done resumes from tomorrow instead.
TODAY = date(2026, 9, 4)


@pytest.fixture
def project(services, make_project):
    """Two 2d human steps in a chain, one independent 1d agent step, dated.

    Human work serialises to 4d whatever the staffing, so at the default 50% focus the
    plan lands eight working days after Monday 7 September 2026.
    """
    services.clock.pin(TODAY)
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Draft the model", "Write the docs"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    read, draft, docs = project.steps
    SetEdgesCommand(draft.id, "requires", [read.id]).redo(library)
    for step, days in ((read, 2.0), (draft, 2.0), (docs, 1.0)):
        SetModuleDataCommand(step.id, ESTIMATION_ID, write_days(days)).redo(library)
    SetModuleDataCommand(docs.id, AGENT_ID, write_state(True)).redo(library)
    SetModuleDataCommand(project.id, ESTIMATION_ID, write_start(date(2026, 9, 7))).redo(library)
    return project


@pytest.fixture
def staged(services, project):
    """The chain closed by two milestones: v1 is the model, v2 a 2d "Ship the docs" on top
    of it and the agent's docs. v1 lands 16 September; v2 begins the 16th, and the agent
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


def _rows(tab):
    """The Milestones page's rows: each milestone's label and where it ends now."""
    return [(row.named.label, row.end) for row in tab.shifts.rows]


def _swatches(tab):
    return [row.named.color for row in tab.shifts.rows]


def _primary(dialog):
    button = dialog.primary()
    assert button is not None
    return button


def _old_plan(draft_id, ship_id, day):
    """The plan as recorded on ``day``: v1 landing the 14th, v2 the 18th, 6d in all."""
    return Snapshot(
        day,
        (
            Stretch(
                draft_id,
                Tally(2, 0, 4.0, 0.0),
                date(2026, 9, 7),
                date(2026, 9, 14),
                (Landing(date(2026, 9, 9), 1, 2.0), Landing(date(2026, 9, 14), 1, 2.0)),
            ),
            Stretch(
                ship_id,
                Tally(1, 0, 2.0, 0.0),
                date(2026, 9, 15),
                date(2026, 9, 18),
                (Landing(date(2026, 9, 18), 1, 2.0),),
            ),
        ),
    )


def _schedule_section(services, step):
    section = MilestoneScheduleSection(services.document, services.undo, lambda: TODAY)
    section.show_target(step.id)
    return section


# -- the figures -----------------------------------------------------------------------------


def test_the_figures_lead_with_where_the_plan_lands_and_how_much_is_done(tab):
    assert tab.landing == date(2026, 9, 16)
    assert tab.landing_figure.text() == "16 September"
    assert tab.moved_figure.text() == ""  # nothing recorded before today to compare with
    assert tab.done_figure.text() == "0% done"
    assert tab.done_figure.toolTip() == "0d of 5d of estimated work done"
    assert not tab.unsized.isVisibleTo(tab.widget)


def test_a_finished_plan_leads_with_the_day_it_was_done(services, project, tab):
    for step in project.steps:
        services.undo.push(
            SetModuleDataCommand(step.id, STATUS_ID, write_status("done", today=TODAY))
        )
    assert tab.landing == TODAY
    assert tab.landing_figure.text() == "✓ 4 September"
    assert tab.done_figure.text() == "100% done"


def test_an_unsized_step_is_counted_and_the_figure_opens_the_estimates_on_it(
    services, project, tab
):
    """The count says what runs as zero, and a click opens the Estimates tab on exactly
    those rows, the keyboard already on the first one's estimate."""
    from dplanner.modules.estimation.bulk import ESTIMATE_COLUMN, BulkEstimateActivity

    read, _draft, _docs = project.steps
    services.undo.push(SetModuleDataCommand(read.id, ESTIMATION_ID, {}))
    assert tab.unsized.isVisibleTo(tab.widget)
    assert tab.unsized.text() == "⚠ 1 unsized"
    assert "Read the spec" in tab.unsized.toolTip()
    tab.unsized.click()
    (estimates,) = [a for a in services.tabs.activities() if isinstance(a, BulkEstimateActivity)]
    assert estimates.filter_key == "unestimated"
    table = estimates.table
    assert table.currentColumn() == ESTIMATE_COLUMN
    assert not table.isRowHidden(table.currentRow())
    shown = [
        item.text()
        for row in range(table.rowCount())
        if (item := table.item(row, 0)) is not None and not table.isRowHidden(row)
    ]
    assert shown == ["Read the spec"]
    services.undo.undo()
    assert not tab.unsized.isVisibleTo(tab.widget)


# -- the pages -------------------------------------------------------------------------------


def test_the_pages_turn_under_one_strip_and_the_tab_opens_on_the_milestones(tab):
    def showing():
        return tab.stack.currentWidget().widget()

    assert tab.page == "milestones" and showing() is tab.shifts
    tab.pages.button("work").click()
    assert tab.page == "work" and showing() is tab.work
    tab.pages.button("calendar").click()
    assert tab.page == "calendar"
    assert showing().isAncestorOf(tab.months)


def test_the_tab_titles_itself_after_the_project(tab):
    assert tab.title == "Discovery — Time Estimates"


# -- the Budget ------------------------------------------------------------------------------


def test_the_budget_stores_the_team_and_a_tab_opened_later_shows_it(services, project, tab):
    """The team is the project's staffing assumption, the focus factor's twin: one
    undoable write, and a tab opened later shows it."""
    assert tab.budget.text() == "Budget · 1p/1a · 50%"
    tab.budget.chosen.emit(2, 3, 0.5)
    assert project.module_data[MODULE_ID] == {"team": [2, 3], "format": 2}
    assert services.undo.undo_text() == "Set Budget"
    assert tab.budget.text() == "Budget · 2p/3a · 50%"
    services.tabs.close_activity(tab)
    again = services.tabs.open("time", project.id)
    assert again.budget.people.value() == 2 and again.budget.agents.value() == 3
    services.undo.undo()
    assert MODULE_ID not in project.module_data
    assert again.budget.text() == "Budget · 1p/1a · 50%"  # the smallest team is the default


def test_a_segment_in_the_budget_is_one_pick_of_what_it_names(project, tab):
    tab.budget.people.button(2).click()
    assert project.module_data[MODULE_ID] == {"team": [2, 1], "format": 2}
    tab.budget.agents.button(3).click()
    assert project.module_data[MODULE_ID] == {"team": [2, 3], "format": 2}


def test_a_picked_focus_re_dates_the_plan_from_today_on(services, project, tab):
    """The focus is written as a float, the plan re-dated, and the focus it replaced kept
    for the work already in flight; the Budget reloads off its own echo's undo."""
    tab.budget.focus.setCurrentIndex(tab.budget.focus.findData(25))
    entry = project.module_data[MODULE_ID]
    assert entry["efficiency"] == 0.25 and isinstance(entry["efficiency"], float)
    assert entry["efficiency_was"]["efficiency"] == 0.5
    assert tab.landing == date(2026, 9, 28)
    assert tab.budget.text() == "Budget · 1p/1a · 25%"
    services.undo.undo()
    assert MODULE_ID not in project.module_data
    assert tab.budget.focus.currentData() == 50


def test_a_foreign_focus_write_refreshes_the_budget_and_the_dates(services, project, tab):
    services.undo.push(
        SetModuleDataCommand(project.id, MODULE_ID, {"efficiency": 0.8, "format": 1})
    )
    assert tab.budget.text() == "Budget · 1p/1a · 80%"
    assert tab.budget.focus.currentData() == 80
    assert tab.landing == date(2026, 9, 11)


def test_without_agent_steps_the_budget_offers_people_alone(services, project, tab):
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.budget.text() == "Budget · 1p · 50%"
    assert tab.budget.agents.isHidden() and tab.budget.agents_caption.isHidden()
    services.undo.undo()
    assert tab.budget.text() == "Budget · 1p/1a · 50%"
    assert not tab.budget.agents.isHidden()


def test_a_separate_instruction_moves_a_step_between_pools(services, project, tab):
    """Typing an agent instruction marks the step as agent work — prose, so the tab has to
    hear ``text_edited`` too."""
    _read, _draft, docs = project.steps
    services.undo.push(SetModuleDataCommand(docs.id, AGENT_ID, {}))
    assert tab.budget.agents.isHidden()
    services.undo.push(EditTextCommand(TextEdit(docs.id, AGENT_ID, 0, "", "Mind the edge cases")))
    assert not tab.budget.agents.isHidden()


def test_unreadable_focus_reads_as_the_default(services, project):
    library = services.document
    for stored in (True, "half", 0.0, 1.5):
        SetModuleDataCommand(project.id, MODULE_ID, {"efficiency": stored, "format": 1}).redo(
            library
        )
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


def test_the_milestones_land_in_sequence(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    assert [row.key for row in tab.shifts.rows] == [draft.id, ship.id]
    assert _rows(tab) == [("v1", date(2026, 9, 16)), ("v2", date(2026, 9, 23))]
    assert tab.landing == date(2026, 9, 23)


def test_each_milestone_wears_its_shade_of_the_palette(services, staged):
    """Two milestones sit a quarter and three quarters of the way along the default map,
    each row named by its label with its step's own title in its words."""
    tab = services.tabs.open("time", staged.id)
    assert _swatches(tab) == shades(PALETTES[0], 2)
    first = tab.shifts.rows[0]
    assert first.named.label == "v1" and first.named.title == "Draft the model"
    assert first.named.badge  # the step's key, worn as a badge in the shade
    assert "v1 — Draft the model" in tab.shifts.words(first)


def test_the_dealt_shades_spread_along_the_map_as_milestones_are_added(services, staged):
    """Shades of one map, dealt by count: a third milestone re-deals the first two, and a
    reader still tells them apart by their place in the sequence."""
    library = services.document
    tab = services.tabs.open("time", staged.id)
    read, _draft, _docs, _ship = staged.steps
    before = _swatches(tab)
    services.undo.push(SetModuleDataCommand(read.id, MILESTONE_ID, write_milestone_label("v0")))
    after = _swatches(tab)
    assert after == shades(PALETTES[0], 3) and before == shades(PALETTES[0], 2)
    assert MODULE_ID not in library.project(staged.id).module_data  # nothing dealt is stored


def test_picking_a_palette_reshades_the_milestones_and_is_undoable(services, staged):
    tab = services.tabs.open("time", staged.id)
    mako = next(found for found in PALETTES if found.id == "mako")
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData("mako"))
    assert staged.module_data[MODULE_ID] == {"palette": "mako", "format": 2}
    assert read_palette(staged) is mako
    assert _swatches(tab) == shades(mako, 2)
    assert tab.months.bands_at(date(2026, 9, 10))[0].color.name() == shades(mako, 2)[0]
    services.undo.undo()
    assert MODULE_ID not in staged.module_data
    assert tab.palette_picker.currentData() == PALETTES[0].id  # the picker follows the model
    assert _swatches(tab) == shades(PALETTES[0], 2)


def test_the_palette_and_the_budget_share_one_entry_without_clobbering(services, staged):
    """Each write keeps the rest, the focus it replaced included: 50% was the day's focus
    when it began, so both changes today remember 50%, the new one counting from tomorrow."""
    was = {"until": "2026-09-05", "efficiency": 0.5}
    tab = services.tabs.open("time", staged.id)
    tab.budget.chosen.emit(1, 1, 0.6)
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData("rocket"))
    assert staged.module_data[MODULE_ID] == {
        "efficiency": 0.6,
        "palette": "rocket",
        "efficiency_was": was,
        "format": 2,
    }
    tab.budget.chosen.emit(1, 1, 0.8)
    assert staged.module_data[MODULE_ID]["efficiency"] == 0.8
    assert staged.module_data[MODULE_ID]["efficiency_was"] == was
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData(PALETTES[0].id))
    assert staged.module_data[MODULE_ID] == {  # the palette's default: absent
        "efficiency": 0.8,
        "efficiency_was": was,
        "format": 2,
    }


def test_picking_a_milestone_holds_it_in_full_ink_and_hides_nothing(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    tab.shifts.picked.emit(ship.id)
    assert tab.picked == ship.id and tab.months.emphasised == ship.id
    assert len(tab.shifts.rows) == 2  # both stay
    tab.shifts.picked.emit(None)
    assert tab.picked is None and tab.months.emphasised is None
    tab.shifts.picked.emit(draft.id)
    services.undo.push(SetModuleDataCommand(draft.id, MILESTONE_ID, {}))  # no longer one
    assert tab.picked is None


def test_removing_a_milestone_step_takes_its_row_with_it(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    services.undo.push(RemoveNodeCommand(ship.id))
    assert [row.key for row in tab.shifts.rows] == [draft.id]
    assert tab.shown is not None
    assert [scope.named.label for scope in tab.shown.stretches] == ["v1", "Remaining work"]


def test_the_rows_follow_the_sequence_when_the_graph_reorders_it(services, staged):
    tab = services.tabs.open("time", staged.id)
    read, draft, _docs, ship = staged.steps
    # Ship now precedes draft in the graph, so its row moves up.
    services.undo.push(SetEdgesCommand(ship.id, "requires", [read.id]))
    services.undo.push(SetEdgesCommand(draft.id, "requires", [ship.id]))
    assert [row.key for row in tab.shifts.rows] == [ship.id, draft.id]


def test_without_milestones_the_page_has_no_rows_and_the_plan_is_still_dated(tab):
    assert tab.shifts.rows == ()
    assert tab.shown is not None and tab.shown.marked == (tab.shown.whole,)
    assert tab.landing == date(2026, 9, 16)


# -- a milestone's Schedule block, on its Details tab ----------------------------------------


def test_only_a_milestone_carries_the_schedule_block(services, staged, step_editor):
    read, draft, _docs, _ship = staged.steps

    def schedule_block(step):
        panel = step_editor(step.id)
        labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
        details = panel._pages.widget(labels.index("Details"))
        return next(b for b in details._blocks if b.section.id == "time_estimates.details")

    assert not schedule_block(draft).isHidden()
    assert schedule_block(read).isHidden()


def test_a_day_of_its_own_holds_the_stretch_back_and_undoes(services, staged):
    """A milestone begins where the one before it lands, unless it is given a day of its
    own; the tab answers each edit, and each undoes."""
    tab = services.tabs.open("time", staged.id)
    _read, _draft, _docs, ship = staged.steps
    section = _schedule_section(services, ship)
    assert not section.own_start.isChecked() and not section.start.isEnabled()
    section.start.setDate(QDate(2026, 10, 5))
    section.own_start.setChecked(True)
    assert ship.module_data[MODULE_ID] == {"start": "2026-10-05", "format": 2}
    assert _rows(tab)[1] == ("v2", date(2026, 10, 9))
    section.own_start.setChecked(False)
    assert MODULE_ID not in ship.module_data
    assert _rows(tab)[1] == ("v2", date(2026, 9, 23))
    section.dispose()


def test_the_colour_verb_offers_the_palettes_shades_then_custom_and_automatic(services, staged):
    _read, draft, _docs, _ship = staged.steps
    section = _schedule_section(services, draft)
    titles = section.colour_labels()
    assert titles[:2] == ["Viridis 1", "Viridis 2"]
    assert titles[-2:] == ["Custom…", "Automatic"]
    assert not section._menu.actions()[-1].isEnabled()  # nothing chosen, nothing to hand back
    section.dispose()


def test_a_chosen_colour_overrides_the_dealt_one_until_automatic(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, _ship = staged.steps
    section = _schedule_section(services, draft)
    section.pick_colour("#C98500")
    assert draft.module_data[MODULE_ID] == {"color": "#c98500", "format": 2}
    assert _swatches(tab)[0] == "#c98500"
    assert tab.months.bands_at(date(2026, 9, 10))[0].color.name() == "#c98500"
    # The other is still dealt in turn — its shade is its place among two, not one.
    assert _swatches(tab)[1] == shades(PALETTES[0], 2)[1]
    section.pick_colour(None)
    assert MODULE_ID not in draft.module_data
    section.dispose()


def test_a_dated_milestone_keeps_its_colour_and_vice_versa(services, staged):
    _read, draft, _docs, _ship = staged.steps
    section = _schedule_section(services, draft)
    section.pick_colour("#c98500")
    section.start.setDate(QDate(2026, 9, 1))
    section.own_start.setChecked(True)
    assert draft.module_data[MODULE_ID] == {
        "start": "2026-09-01",
        "color": "#c98500",
        "format": 2,
    }
    section.pick_colour(None)
    assert draft.module_data[MODULE_ID] == {"start": "2026-09-01", "format": 2}
    section.dispose()


# -- what breaks, said plainly ---------------------------------------------------------------


def test_a_loop_in_the_file_says_which_steps_wait_on_each_other(services, project, tab):
    """The model refuses a cycle; a file does not. Write one behind its back."""
    library = services.document
    read, draft, _docs = project.steps
    read.edges["requires"] = [draft.id]
    library.edges_changed.emit(read.id, None)
    assert not tab.stack.isVisibleTo(tab.widget)
    assert "Read the spec, Draft the model" in tab.problem.words()
    assert "Unlink one" in tab.problem.words() and tab.problem.tone() == "error"
    read.edges["requires"] = []
    library.edges_changed.emit(read.id, None)
    assert tab.stack.isVisibleTo(tab.widget) and tab.problem.words() == ""
    assert tab.landing == date(2026, 9, 16)


def test_a_stepless_project_says_so_instead_of_a_page_of_zeros(services, make_project):
    empty = make_project("Empty")
    tab = services.tabs.open("time", empty.id)
    assert tab.empty.isVisibleTo(tab.widget) and tab.empty.text() == NO_STEPS
    assert tab.controls.isVisibleTo(tab.widget)  # the strip is chrome, and stays


# -- the calendar ----------------------------------------------------------------------------


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
    tab.budget.chosen.emit(2, 2, 0.5)  # a re-render keeps the paged window
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
    """Three months across at most, two rows of them; the cells grow with the width."""
    tab.pages.button("calendar").click()
    tab.months.resize(700, 100)
    assert tab.months.columns == 3
    assert tab.months.cell_size == 28
    assert tab.months.month_count == 6
    tab.months.resize(200, 100)
    assert tab.months.columns == 1
    assert tab.months.cell_size == 26
    assert tab.months.month_count == 6


def test_the_calendar_answers_height_for_width_and_never_resizes_itself(app, staged, tab):
    """The layout asks how tall the calendar is for a width; the calendar never sets its
    own height in its resize event. That distinction is what keeps a scroll area from
    looping — the height toggles the scrollbar, the scrollbar changes the width, the
    width changes the height — which once ran the process 184,800 frames deep."""
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    months = tab.months
    assert months.hasHeightForWidth()
    narrow, wide = months.heightForWidth(200), months.heightForWidth(700)
    assert narrow > wide  # One column stacks the months; three across need fewer rows.
    assert months.sizeHint().height() == months.heightForWidth(months.minimumWidth())
    # One row is the least it can need; the rest is asked through heightForWidth.
    assert months.minimumSizeHint().height() < months.heightForWidth(months.minimumWidth())

    # The shape that looped: a resizable scroll area whose content height sits right at
    # the viewport's, swept across every width that could flip the scrollbar.
    page = QWidget()
    layout = QVBoxLayout(page)
    other = tab.months.__class__(months._today, page)
    other.show_bands(months._start, months._bands, months._today)
    layout.addWidget(other)
    layout.addStretch(1)
    scroller = QScrollArea()
    scroller.setWidgetResizable(True)
    scroller.setWidget(page)
    scroller.show()
    for width in range(180, 720, 4):
        scroller.resize(width, other.heightForWidth(width) + 20)
        app.processEvents()
    assert other.columns >= 1
    scroller.close()
    scroller.deleteLater()


def test_the_calendar_paints_each_stretch_and_marks_the_landing(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    (first,) = tab.months.bands_at(date(2026, 9, 10))
    (second,) = tab.months.bands_at(date(2026, 9, 21))
    assert first.key == draft.id and first.label == "v1"
    assert second.key == ship.id
    assert [first.color.name(), second.color.name()] == shades(PALETTES[0], 2)
    # v2 begins the afternoon v1 lands: the day is both, and the landing is what it shows.
    assert tab.months.bands_at(date(2026, 9, 16)) == (first, second)
    assert "v1 lands; v2 starts, working day 1 of 6" in tab.months.day_tooltip(date(2026, 9, 16))
    assert "v2, working day 2 of 6" in tab.months.day_tooltip(date(2026, 9, 17))
    assert "v2 lands" in tab.months.day_tooltip(date(2026, 9, 23))


def test_two_milestones_worked_at_once_share_their_days_on_the_calendar(services, staged):
    """The agent starts v2's docs the Friday before, while v1's model is still to come: from
    then until v1 lands both stretches are being worked, and each such day is both."""
    read, draft, docs, ship = staged.steps
    tab = services.tabs.open("time", staged.id)
    for step, status in ((read, "done"), (docs, "in-progress")):
        services.undo.push(
            SetModuleDataCommand(step.id, STATUS_ID, write_status(status, today=TODAY))
        )
    shared = tab.months.bands_at(date(2026, 9, 8))
    assert [band.key for band in shared] == [draft.id, ship.id]
    assert tab.months.day_tooltip(date(2026, 9, 8)) == (
        "Tuesday 8 September — v1, working day 3 of 5; v2, working day 3 of 9"
    )


def test_milestones_landing_on_one_day_share_one_mark_and_one_name(services, staged):
    """Everything done today: v1 and v2 land together, so the Work page, the calendar and
    the report each mark the day once — a wedge each in the report, which a click reads —
    and name both."""
    from dplanner.cli.report.drawings import LIGHT, chart_svg
    from dplanner.cli.report.parts import Chart
    from dplanner.modules import _time_readers
    from dplanner.modules.time_estimates.report import report_source

    tab = services.tabs.open("time", staged.id)
    for step in staged.steps:
        services.undo.push(
            SetModuleDataCommand(step.id, STATUS_ID, write_status("done", today=TODAY))
        )
    shown = tab.shown
    assert shown is not None
    (landing,) = shown.landings
    assert [scope.named.label for scope in landing] == ["v1", "v2"]
    work = tab.work
    work.resize(900, work.height())
    work.grab()
    (hit,) = [hit for hit in work._hits if "v1" in hit.words]
    assert "v2" in hit.words
    assert "v1 lands; v2 lands" in tab.months.day_tooltip(TODAY)
    contribution = report_source(_time_readers())(
        services.document, staged, services.repo.files, TODAY
    )
    (chart,) = [placed.part for placed in contribution.placed if isinstance(placed.part, Chart)]
    assert len(chart.landings) == 1
    svg = chart_svg(chart, LIGHT)
    assert svg.count('class="landing"') == 1 and svg.count('class="wedge"') == 2
    assert f'<g data-step="{staged.steps[3].id}"><path class="wedge"' in svg
    assert ">v1 · v2</text>" in svg


# -- the Work page ---------------------------------------------------------------------------


def test_the_work_page_reads_the_recorded_days_and_the_schedule_from_today(services, staged):
    """The spec, read the Friday before the plan starts: the scope holds 7d, 2d of it done,
    and the plan's schedule runs on from today to where the rest lands — the 17th, a day
    sooner, since the work resumes on the Monday."""
    read, draft, _docs, ship = staged.steps
    tab = services.tabs.open("time", staged.id)
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    shown = tab.shown
    assert shown is not None
    assert shown.burnup.scope[-1] == (TODAY, 7.0) and shown.burnup.done[-1] == (TODAY, 2.0)
    assert shown.schedule[0] == (TODAY, 2.0) and shown.schedule[-1] == (date(2026, 9, 17), 7.0)
    assert shown.scale == 7.5  # a little headroom over the most work either plot holds
    assert TODAY in shown.burnup.active  # a status changed today
    assert [(scope.key, scope.end) for scope in shown.marked] == [
        (draft.id, date(2026, 9, 10)),
        (ship.id, date(2026, 9, 17)),
    ]
    work = tab.work
    work.resize(900, work.height())
    axis = work.axis()
    said = work.reading(axis.x(TODAY) + 1, work.work_top + 10)
    assert said.startswith("4 September") and "scope: 7d" in said and "done: 2d" in said


def test_the_scope_is_compared_with_the_plan_the_strip_names(services, staged):
    """A step and a day of work more than the plan recorded on the 1st: the scope reads
    warm against it, and the day it rose carries one ▲ in words."""
    library = services.document
    _read, draft, _docs, ship = staged.steps
    old = _old_plan(draft.id, ship.id, date(2026, 9, 1))
    SetModuleDataCommand(staged.id, HISTORY_ID, write_history([old])).redo(library)
    tab = services.tabs.open("time", staged.id)
    shown = tab.shown
    assert shown is not None and shown.compared
    assert shown.burnup.baseline == 6.0 and shown.burnup.scope[-1] == (TODAY, 7.0)
    (mark,) = shown.burnup.marks
    assert mark.up and (mark.steps, mark.days) == (1, 1.0)


# -- the Milestones page, against the plan compared with -------------------------------------


def test_each_landing_is_compared_with_the_plan_the_strip_names(services, staged):
    """The then side reads the plan at the project's start unless picked otherwise — the
    plan a week ago, a day, a saved snapshot — and the picker's tooltip names the record
    that stood in, so the comparison is never a guess."""
    library = services.document
    _read, draft, _docs, ship = staged.steps
    old = _old_plan(draft.id, ship.id, date(2026, 9, 1))
    SetModuleDataCommand(staged.id, HISTORY_ID, write_history([old])).redo(library)
    tab = services.tabs.open("time", staged.id)
    assert tab.then_pick.kind == "start" and tab.then_picker.text() == "Plan at start"
    # The start is the 7th; the record that stands in for it is the 1st's, and it says so.
    assert tab.then_picker.toolTip() == "the plan at start, recorded 1 September"
    assert not tab.controls.is_shown(tab.then_day)
    assert [(row.then, row.planned) for row in tab.shifts.rows] == [
        (date(2026, 9, 14), date(2026, 9, 16)),
        (date(2026, 9, 18), date(2026, 9, 23)),
    ]
    assert tab.shown is not None and tab.shown.whole.moved == 3
    assert tab.moved_figure.text() == "▶ +3d"
    words = tab.shifts.words(tab.shifts.rows[1])
    assert "then: 18 Sep" in words and "plan now: 23 Sep" in words
    # The plan a week ago: nothing was recorded that early, so the earliest record stands in.
    assert tab.then_picker.menu_labels() == ["Plan at start", "Plan a week ago", "Day…"]
    tab.then_picker.picked.emit(Pick("week"))
    assert tab.then_picker.text() == "Plan a week ago"
    assert tab.then_picker.toolTip() == "the plan a week ago, recorded 1 September"
    # Day…: the field appears beside the picker, and the pick follows it.
    tab.then_picker.picked.emit(Pick("day", day=date(2026, 9, 3)))
    assert tab.then_pick == Pick("day", day=date(2026, 9, 3))
    assert tab.controls.is_shown(tab.then_day) and tab.then_picker.text() == "3 September"
    assert tab.then_picker.toolTip() == "the plan at 3 September, recorded 1 September"
    tab.then_day.setDate(QDate(2030, 1, 1))
    assert tab.then_pick.day == date(2030, 1, 1) and tab.shown.compared
    tab.then_picker.picked.emit(Pick("start"))
    assert tab.then_pick.kind == "start" and not tab.controls.is_shown(tab.then_day)


def test_a_snapshot_saved_on_purpose_is_named_kept_and_compared_against(services, staged):
    """Save snapshot… keeps the plan as it stands under a title — one undoable write that
    leaves the recorder's day alone — and the picker then offers it, the page comparing
    against it. Forgetting it takes it out of the menu."""
    from dplanner.modules.time_estimates.snapshots import SaveSnapshotDialog

    read, _draft, _docs, ship = staged.steps
    tab = services.tabs.open("time", staged.id)
    dialog = SaveSnapshotDialog([row.title for row in read_saved(staged)], tab.widget)
    assert not _primary(dialog).isEnabled()
    dialog.title.setText("Kickoff review")
    dialog.note.setPlainText("What we thought on day one")
    assert _primary(dialog).isEnabled()
    assert dialog.values() == ("Kickoff review", "What we thought on day one")
    dialog.deleteLater()
    tab.save_snapshot_as("Kickoff review", "What we thought on day one")
    assert services.undo.undo_text().endswith("Save Snapshot")
    (kept,) = read_saved(staged)
    assert kept.title == "Kickoff review" and kept.day == TODAY
    assert kept.same_plan(read_history(staged)[-1])
    assert len(read_history(staged)) == 1  # the automatic day is untouched
    assert tab.shown is not None and tab.shown.saved == ((TODAY, "Kickoff review"),)
    # A taken title is refused in the dialog, with the reason under the field.
    again = SaveSnapshotDialog(["Kickoff review"], tab.widget)
    again.title.setText("kickoff review")
    assert not _primary(again).isEnabled()
    assert "already saved" in again.reason.words() and again.reason.tone() == "error"
    again.deleteLater()
    assert tab.then_picker.menu_labels()[2].startswith("Kickoff review · ")
    # Work lands and the plan grows; the saved snapshot is what the page compares against.
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    services.undo.push(SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(4.0)))
    tab.then_picker.picked.emit(Pick("saved", title="Kickoff review"))
    shown = tab.shown
    assert tab.then_picker.text() == "Kickoff review"
    assert shown.basis == f"Kickoff review ({format_date(TODAY, TODAY)})"
    # The spec, read before the plan began, saved the four days that two more of shipping cost.
    assert shown.whole.then == date(2026, 9, 23) and shown.whole.planned == date(2026, 9, 23)
    assert shown.burnup.baseline == 7.0 and shown.burnup.scope[-1] == (TODAY, 9.0)
    # Forgetting it is undoable too.
    tab.then_picker.picked.emit(Pick("start"))
    tab.then_picker.forget.emit("Kickoff review")
    assert services.undo.undo_text().endswith("Forget Snapshot")
    assert read_saved(staged) == [] and tab.shown.saved == ()
    services.undo.undo()
    assert [row.title for row in read_saved(staged)] == ["Kickoff review"]
    assert staged.module_data[HISTORY_ID]["format"] == 3
    before = services.undo.undo_text()
    tab.then_picker.forget.emit("nobody")  # nothing to forget: nothing pushed
    assert services.undo.undo_text() == before


# -- History ---------------------------------------------------------------------------------


def test_history_reads_an_earlier_days_record_and_nothing_on_the_page_writes(services, staged):
    """The slider runs over the recorded days and today. On an earlier day the page reads
    that day's record in the live plan's place — the axes holding still — and every writer
    is greyed, saying why, until the page is back on today."""
    library = services.document
    _read, draft, _docs, ship = staged.steps
    old = _old_plan(draft.id, ship.id, date(2026, 9, 1))
    SetModuleDataCommand(staged.id, HISTORY_ID, write_history([old])).redo(library)
    tab = services.tabs.open("time", staged.id)
    history = tab.history
    assert history.text() == "History" and not history.looking_back
    assert history.days.value() == 1  # the 1st's record, then today's
    assert "1 recorded day, from 1 Sep" in history.how_many.text()
    reach = tab.shown.reach
    history.days.set_value(0, say=True)
    assert tab.as_of == date(2026, 9, 1) and tab.shown.day == date(2026, 9, 1)
    assert tab.landing == date(2026, 9, 18)  # as the record had it
    assert tab.shown.reach == reach  # the axes held still
    assert history.text() == "History · 1 Sep" and history.said.text().startswith("as recorded")
    assert tab.controls.is_shown(tab.back_to_today)
    why = tab.writers_refusal()
    assert why.startswith("Showing the plan as recorded 1 September")
    assert not tab.budget.isEnabled() and tab.budget.toolTip() == why
    assert not tab.more.isEnabled() and not tab.save_snapshot.isEnabled()
    assert not tab.months.pickable
    tab.months.day_picked.emit(date(2026, 9, 14))  # a click cannot write either
    assert staged.module_data[ESTIMATION_ID]["start"] == "2026-09-07"
    assert not tab.unsized.isVisibleTo(tab.widget)
    tab.back_to_today.click()
    assert tab.as_of is None and tab.landing == date(2026, 9, 23)
    assert tab.writers_refusal() == "" and tab.budget.isEnabled() and tab.months.pickable
    assert not tab.controls.is_shown(tab.back_to_today) and history.text() == "History"


def test_history_with_nothing_recorded_before_today_has_only_today(tab):
    assert tab.history.days.slider.maximum() == 0
    assert tab.history.how_many.text() == "Nothing recorded before today yet."


def test_a_host_may_grey_the_writers_for_a_reason_of_its_own(tab):
    tab.set_read_only("Not here")
    assert tab.writers_refusal() == "Not here" and not tab.budget.isEnabled()
    tab.set_read_only("")
    assert tab.budget.isEnabled()


# -- Adjust for Efficiency -------------------------------------------------------------------


@pytest.fixture
def slow(services, make_project):
    """Three 1d steps that each took one of three people four working days at 50% focus —
    two planned — then a 4d step to go, read on the Wednesday after: people run at
    two-thirds of the plan."""
    from dplanner.framework.user_config import set_global
    from dplanner.modules.time_estimates.activity import ADJUST_KEY

    services.clock.pin(date(2026, 9, 16))
    library = services.document
    project = make_project("Slow")
    for title, days in (("A", 1.0), ("B", 1.0), ("C", 1.0), ("D", 4.0)):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, ESTIMATION_ID, write_days(days)).redo(library)
    *finished, last = project.steps
    SetEdgesCommand(last.id, "requires", [step.id for step in finished]).redo(library)
    for step in finished:
        began = write_status("in-progress", today=date(2026, 9, 7))
        entry = write_status("done", today=date(2026, 9, 10), previous=began)
        SetModuleDataCommand(step.id, STATUS_ID, entry).redo(library)
    SetModuleDataCommand(project.id, ESTIMATION_ID, write_start(date(2026, 9, 7))).redo(library)
    SetModuleDataCommand(project.id, MODULE_ID, {"team": [3, 1]}).redo(library)
    yield project
    set_global(MODULE_ID, ADJUST_KEY, False)  # a preference: the next test starts off


def test_adjusting_for_efficiency_re_dates_the_rest_at_the_pace_so_far(services, slow):
    """The toggle says the focus measured beside the planned one, and pressed it re-dates
    people's remaining work at it — on the page alone: the recorder keeps the plan as its
    stored focus dates it, and so does a snapshot saved while it is on."""
    tab = services.tabs.open("time", slow.id)
    assert tab.pace == pytest.approx(2 / 3)
    assert tab.adjust.isEnabled() and not tab.adjust.isChecked()
    assert tab.adjust.text() == "Adjust for Efficiency · 33%"
    assert "1.5\N{MULTIPLICATION SIGN} their estimates" in tab.adjust.toolTip()
    planned = tab.landing
    assert planned is not None
    tab.adjust.click()
    assert tab.adjusting and tab.adjust.isChecked()
    assert tab.landing is not None and tab.landing > planned
    assert "at the pace so far" in tab.landing_figure.toolTip()
    assert read_history(slow)[-1].landing(None) == planned  # the record is the plan's
    tab.save_snapshot_as("Mid-sprint")
    assert read_saved(slow)[0].landing(None) == planned
    tab.adjust.click()
    assert not tab.adjusting and tab.landing == planned


def test_adjusting_waits_for_enough_to_go_on_and_stands_down_while_looking_back(services, slow):
    from dataclasses import replace

    library = services.document
    live = services.tabs.open("time", slow.id).snapshot()
    assert live is not None
    earlier = replace(live, day=date(2026, 9, 8))
    SetModuleDataCommand(slow.id, HISTORY_ID, write_history([earlier])).redo(library)
    tab = services.tabs.open("time", slow.id)
    tab.adjust.click()
    assert tab.adjusting
    tab.history.days.set_value(0, say=True)
    assert not tab.adjust.isEnabled() and not tab.adjust.isChecked() and not tab.adjusting
    assert "back to today to adjust" in tab.adjust.toolTip()
    tab.back_to_today.click()
    assert tab.adjusting and tab.adjust.isChecked()  # the preference was kept all along
    services.clock.pin(date(2026, 9, 11))  # too early: four working days of work
    assert tab.pace is None and not tab.adjust.isEnabled() and not tab.adjusting
    assert tab.adjust.toolTip().startswith("Adjusting for efficiency needs 5 working days")


# -- waits on the page -----------------------------------------------------------------------


def test_a_wait_is_hatched_on_the_work_page_and_the_calendar_and_named_in_its_milestone(
    services, staged
):
    """Hardware arrives on the 21st, in v2's stretch: the plan dates the wait's days, the
    Work page and the calendar say it where the pointer is, and v2's words name it."""
    from dplanner.cli.report.drawings import LIGHT, chart_svg
    from dplanner.cli.report.parts import Chart
    from dplanner.domain.schedule import Wait
    from dplanner.modules import _time_readers
    from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
    from dplanner.modules.step_wait.aspect import write as write_wait
    from dplanner.modules.time_estimates.report import report_source

    library = services.document
    _read, draft, _docs, ship = staged.steps
    wait = Step(title="Hardware arrives")
    AddNodeCommand(staged.id, wait).redo(library)
    SetModuleDataCommand(wait.id, WAIT_ID, write_wait(Wait(until=date(2026, 9, 21)))).redo(library)
    SetEdgesCommand(wait.id, "requires", [draft.id]).redo(library)
    SetEdgesCommand(ship.id, "requires", [*ship.edges["requires"], wait.id]).redo(library)
    tab = services.tabs.open("time", staged.id)
    (held,) = tab.shown.now.waits
    assert (held.key, held.title, held.end) == (ship.id, "Hardware arrives", date(2026, 9, 18))
    work = tab.work
    work.resize(900, work.height())
    axis = work.axis()
    assert "waits: Hardware arrives" in work.reading(axis.x(held.end), work.work_top + 10)
    assert "waits: Hardware arrives" in tab.months.day_tooltip(held.end)
    assert "waits: Hardware arrives" in tab.shifts.words(tab.shifts.rows[1])
    assert "waits:" not in tab.shifts.words(tab.shifts.rows[0])
    contribution = report_source(_time_readers())(library, staged, services.repo.files, TODAY)
    (chart,) = [placed.part for placed in contribution.placed if isinstance(placed.part, Chart)]
    assert chart.waits == ((held.start, held.end, "Hardware arrives"),)
    assert chart_svg(chart, LIGHT).count('class="wait"') == 2  # a band in each work plot


# -- the recorder ----------------------------------------------------------------------------


def test_the_recorder_writes_the_day_once_off_the_undo_stack(services, staged):
    """A settled change records the day's row — once, replaced within the day, never
    when nothing changed — and Ctrl+Z undoes the status, not the record."""
    read, _draft, _docs, _ship = staged.steps
    (row,) = read_history(staged)  # the window opened on the plan and recorded it
    assert row.day == TODAY and row.toward(None).done == 0
    before = services.undo.undo_text()
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    (row,) = read_history(staged)
    assert row.toward(None).done == 1
    assert services.undo.undo_text() != before  # the status is the undo step, the record is not
    services.undo.undo()
    assert STATUS_ID not in read.module_data
    (row,) = read_history(staged)
    assert row.toward(None).done == 0  # the record follows the plan, on the same day
    services.undo.redo()
    assert read_history(staged)[0].toward(None).done == 1
    entry = staged.module_data[HISTORY_ID]
    assert entry["format"] == 3 and len(entry["days"]) == 1


def test_a_step_started_today_makes_today_a_day_of_work(services, staged):
    """Nothing landed, but a status moved: the day's row counts it, so the day is told
    from one on which nothing happened."""
    read, *_rest = staged.steps
    (row,) = read_history(staged)
    assert row.changed == 0
    entry = write_status("in-progress", today=TODAY, previous=read.module_data.get(STATUS_ID))
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, entry))
    (row,) = read_history(staged)
    assert row.changed == 1 and row.toward(None).done == 0


def test_a_turned_day_re_dates_the_tab_and_is_recorded(services, project, tab):
    """An undated plan starts today, so the day turning moves it with nothing edited: the
    tab re-dates on the clock's word, and the recorder writes the new day's row."""
    SetModuleDataCommand(project.id, ESTIMATION_ID, write_start(None)).redo(services.document)
    landing = tab.landing
    assert tab.snapshot().day == TODAY and read_history(project)[-1].day == TODAY
    monday = date(2026, 9, 7)
    services.clock.pin(monday)
    # Eight working days from Friday the 4th land on the 15th; from the Monday, a day later.
    assert landing == date(2026, 9, 15) and tab.landing == date(2026, 9, 16)
    assert tab.snapshot().day == monday
    assert [row.day for row in read_history(project)] == [TODAY, monday]


def test_the_strip_says_updating_until_the_page_has(services, staged, tab):
    """A change arrives, the page waits for the burst to settle, and the strip says so in
    between — and stops saying so the moment the page has re-run. The indicator follows
    the debouncer itself (``pending_changed``), so this holds for a rebuild that raises as
    much as one that returns."""
    services.debounce.set_immediate(False)
    try:
        assert tab.updating.isHidden()
        ship = staged.steps[-1]
        services.undo.push(SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(9.0)))
        assert not tab.updating.isHidden()
        services.debounce.flush_all()
        assert tab.updating.isHidden()
        assert tab.landing == date(2026, 10, 13)
    finally:
        services.debounce.set_immediate(True)
