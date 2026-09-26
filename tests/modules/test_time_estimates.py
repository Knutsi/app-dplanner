"""The time estimates tab: the staffing picker, the start dates and the milestones on the
left, the calendar and the plots they date on the right, a page at a time, under one
strip that names the two snapshots the plots compare."""

from datetime import date

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateEdit

from dplanner.domain.commands import (
    AddNodeCommand,
    EditTextCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step, TextEdit
from dplanner.domain.schedule import format_date
from dplanner.framework.list_rows import DETAIL_ROLE, MUTED_ROLE, VALUE_ROLE
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as write_days
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as write_milestone_label
from dplanner.modules.time_estimates.chart import segment_words
from dplanner.modules.time_estimates.milestones import (
    ALL_KEY,
    ALL_LABEL,
    BEGINS_COLUMN,
    COLOR_ROLE,
    DAYS_COLUMN,
    LANDED_COLUMN,
    LANDS_COLUMN,
)
from dplanner.modules.time_estimates.module import NO_STEPS
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    read_efficiency,
    read_palette,
    stretched,
)
from dplanner.modules.time_estimates.view import TINT_MIN_ALPHA
from dplanner.theme.palettes import PALETTES, shades

# The day every test here is run on, so no date the tab prints depends on the day the suite
# runs: the Friday before the plan starts, when nothing is due yet and the plan's own dates
# stand — a plan whose days have passed with nothing done resumes from tomorrow instead.
TODAY = date(2026, 9, 4)


@pytest.fixture
def project(services, make_project):
    """Two 2d human steps in a chain, one independent 1d agent step, dated.

    Human work serialises to 4d whatever the staffing, so every parallel cell reads 4d
    and — at the default 50% focus — every calendar cell reads 8d, landing eight working
    days after Monday 7 September 2026.
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


def _cell(tab, row, column):
    item = tab.milestones.item(row, column)
    assert item is not None
    return item


def _row(tab, key):
    row = tab.milestones.row_of(key)
    assert row is not None
    return row


def _landings(tab):
    return [
        (
            _cell(tab, row, 0).text(),
            _cell(tab, row, LANDS_COLUMN).text(),
            _cell(tab, row, DAYS_COLUMN).text(),
        )
        for row in range(tab.milestones.rowCount())
    ]


def _swatches(tab):
    """The milestone rows' colours, top to bottom — the whole and the remainder aside."""
    keys = tab.milestones.keys
    return [
        _cell(tab, row, 0).data(COLOR_ROLE)
        for row in range(tab.milestones.rowCount())
        if tab.milestones.key_at(row) in keys
    ]


def _primary(dialog):
    button = dialog.primary()
    assert button is not None
    return button


def _begin(tab, key, day):
    """Type a day into a row's Begins cell and commit it, as Enter would."""
    table = tab.milestones
    index = table.model().index(_row(tab, key), BEGINS_COLUMN)
    if table.indexWidget(index) is None:
        table.edit(index)
    field = table.indexWidget(index)
    assert isinstance(field, QDateEdit)
    field.setDate(QDate(day.year, day.month, day.day))
    table.commitData(field)


# -- the grid and the answer -----------------------------------------------------------------


def test_the_default_team_dates_the_plan_in_the_landing_list(tab):
    assert tab.landing == date(2026, 9, 16)
    assert tab.matrix.value_at(1, 1) == "1.6w"
    assert _landings(tab) == [("All work", "16 September", "1.6w")]  # one stretch, no whole
    assert not tab.banner.isVisibleTo(tab.widget)


def test_selecting_a_tile_re_asks_the_question(tab):
    tab.matrix.select(2, 3)
    assert "2 people + 3 agents" in tab.matrix.tooltip_for(
        next(cell for cell in tab._report.calendar if (cell.humans, cell.agents) == (2, 3))
    )
    assert tab.landing == date(2026, 9, 16)  # the chain does not care


def test_the_lens_toggle_swaps_the_grid_not_the_answer(tab):
    tab.lens_box.setCurrentIndex(1)  # Project days.
    assert tab.matrix.value_at(1, 1) == "4d"  # project working days now
    assert tab.landing == date(2026, 9, 16)  # the calendar keeps its dates
    tab.lens_box.setCurrentIndex(0)  # Calendar days.
    assert tab.matrix.value_at(1, 1) == "1.6w"


def test_the_matrix_follows_the_graph(services, project, tab):
    """Nothing is stored: unlinking the chain halves the makespan with two humans."""
    tab.lens_box.setCurrentIndex(1)  # Project days.
    _read, draft, _docs = project.steps
    services.undo.push(SetEdgesCommand(draft.id, "requires", []))
    assert tab.matrix.value_at(1, 1) == "4d"  # one human still serialises
    assert tab.matrix.value_at(2, 1) == "2d"
    services.undo.undo()
    assert tab.matrix.value_at(2, 1) == "4d"


def test_more_time_wears_more_ink_and_the_floor_is_lightest(services, project, tab):
    """With the chain broken, one human sits above the 2d floor and two humans on it."""
    tab.lens_box.setCurrentIndex(1)  # Project days.
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


def test_the_calendar_answers_height_for_width_and_never_resizes_itself(app, staged, tab):
    """The layout asks how tall the calendar is for a width; the calendar never sets its
    own height in its resize event. That distinction is what keeps a scroll area from
    looping — the height toggles the scrollbar, the scrollbar changes the width, the
    width changes the height — which once ran the process 184,800 frames deep."""
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    months = tab.months
    assert months.hasHeightForWidth()
    narrow, wide = months.heightForWidth(200), months.heightForWidth(700)
    assert narrow > wide  # One column stacks the months; four across need fewer rows.
    assert months.sizeHint().height() == months.heightForWidth(months.minimumWidth())

    # The shape that looped: a resizable scroll area whose content height sits right at
    # the viewport's, swept across every width that could flip the scrollbar.
    page = QWidget()
    layout = QVBoxLayout(page)
    other = tab.months.__class__(months._today, page)
    other.show_bands(*_bands_of(months))
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


def _bands_of(months):
    """What a calendar was last shown, so a second one can be shown the same."""
    return months._start, months._bands, months._today


def test_an_unestimated_step_is_noted_and_the_banner_opens_the_estimates_on_it(
    services, project, tab
):
    """The banner over the answer counts what runs as zero, and its button opens the
    Estimates tab on exactly those rows."""
    from dplanner.modules.estimation.bulk import BulkEstimateActivity

    read, _draft, _docs = project.steps
    services.undo.push(SetModuleDataCommand(read.id, ESTIMATION_ID, {}))
    assert tab.banner.isVisibleTo(tab.widget)
    assert tab.banner.note.words() == "1 step unestimated · counted as 0d"
    assert tab.banner.button.text() == "Estimate missing"
    tab.banner.button.click()
    (estimates,) = [a for a in services.tabs.activities() if isinstance(a, BulkEstimateActivity)]
    assert estimates.filter_key == "unestimated"
    # And the keyboard is already on the first unsized row's estimate.
    from dplanner.modules.estimation.bulk import ESTIMATE_COLUMN

    assert estimates.table.currentColumn() == ESTIMATE_COLUMN
    assert not estimates.table.isRowHidden(estimates.table.currentRow())
    table = estimates.table
    shown = [
        item.text()
        for row in range(table.rowCount())
        if (item := table.item(row, 0)) is not None and not table.isRowHidden(row)
    ]
    assert shown == ["Read the spec"]
    services.undo.undo()
    assert not tab.banner.isVisibleTo(tab.widget)


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
    services.undo.push(EditTextCommand(TextEdit(docs.id, AGENT_ID, 0, "", "Mind the edge cases")))
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


def test_the_milestones_land_in_sequence_and_the_whole_leads_the_list(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    assert tab.milestones.keys == (draft.id, ship.id)
    assert _landings(tab) == [
        ("All milestones", "23 September", "2.6w"),  # 13 working days, 7 → 23 September
        ("v1", "16 September", "1.6w"),
        ("v2", "23 September", "6d"),  # from the 16th, the moment v1 lands
    ]
    assert tab.milestones.key_at(0) == ALL_KEY
    assert tab.milestones.picked_key() == ALL_KEY  # nothing picked: the whole is
    assert _cell(tab, 0, BEGINS_COLUMN).data(VALUE_ROLE) == date(2026, 9, 7)
    assert tab.landing == date(2026, 9, 23)


def test_a_stretch_prints_whole_days_never_the_simulation_fraction(services, staged):
    """At 60% focus a 2d step stretches to 3.33d; two of them land in seven working days,
    and seven is what the list says — not 6.66667."""
    tab = services.tabs.open("time", staged.id)
    tab.focus_bar.percent.setValue(60)
    assert _landings(tab)[1] == ("v1", "15 September", "7d")


def test_each_milestone_wears_its_shade_of_the_palette(services, staged):
    """Two milestones sit a quarter and three quarters of the way along the default map."""
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    first, second = shades(PALETTES[0], 2)
    assert _cell(tab, _row(tab, draft.id), 0).data(COLOR_ROLE) == first
    assert _cell(tab, _row(tab, ship.id), 0).data(COLOR_ROLE) == second
    name = _cell(tab, _row(tab, draft.id), 0)
    assert name.text() == "v1" and not name.icon().isNull()  # The key badge, in its shade.
    assert name.data(DETAIL_ROLE) == "Draft the model"  # The step's own title under the label.


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
    assert len(set(after)) == 3
    assert MODULE_ID not in library.project(staged.id).module_data  # nothing dealt is stored


def test_picking_a_palette_reshades_the_milestones_and_is_undoable(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    mako = next(found for found in PALETTES if found.id == "mako")
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData("mako"))
    assert staged.module_data[MODULE_ID] == {"palette": "mako", "format": 2}
    assert read_palette(staged) is mako
    assert _swatches(tab) == shades(mako, 2)
    assert tab.months.band_at(date(2026, 9, 10)).color.name() == shades(mako, 2)[0]
    services.undo.undo()
    assert MODULE_ID not in staged.module_data
    assert tab.palette_picker.palette_id == PALETTES[0].id  # the picker follows the model
    assert _cell(tab, _row(tab, draft.id), 0).data(COLOR_ROLE) == shades(PALETTES[0], 2)[0]
    assert _cell(tab, _row(tab, ship.id), 0).data(COLOR_ROLE) == shades(PALETTES[0], 2)[1]


def test_the_palette_and_the_focus_factor_share_one_entry_without_clobbering(services, staged):
    """Each write keeps the rest, the focus it replaced included: 50% was the day's focus
    when it began, so both changes today remember 50%, the new one counting from tomorrow."""
    was = {"until": "2026-09-05", "efficiency": 0.5}
    tab = services.tabs.open("time", staged.id)
    tab.focus_bar.percent.setValue(60)
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData("rocket"))
    assert staged.module_data[MODULE_ID] == {
        "efficiency": 0.6,
        "palette": "rocket",
        "efficiency_was": was,
        "format": 2,
    }
    tab.focus_bar.percent.setValue(80)
    assert staged.module_data[MODULE_ID] == {
        "efficiency": 0.8,
        "palette": "rocket",
        "efficiency_was": was,
        "format": 2,
    }
    tab.palette_picker.setCurrentIndex(tab.palette_picker.findData(PALETTES[0].id))
    assert staged.module_data[MODULE_ID] == {  # the palette's default: absent
        "efficiency": 0.8,
        "efficiency_was": was,
        "format": 2,
    }


def test_the_colour_verb_offers_the_palettes_shades_then_custom_and_automatic(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, _ship = staged.steps
    assert tab.colour_menu() is None and not tab.colour_action.isEnabled()  # Nothing picked.
    tab.milestones.selectRow(_row(tab, draft.id))
    assert tab.colour_action.isEnabled()
    menu = tab.colour_menu()
    assert menu is not None
    titles = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert titles[:2] == ["Viridis 1", "Viridis 2"]
    assert titles[-2:] == ["Custom…", "Automatic"]
    assert not menu.actions()[-1].isEnabled()  # nothing chosen yet, so nothing to hand back


def test_the_calendar_paints_each_stretch_and_marks_the_landing(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    first = tab.months.band_at(date(2026, 9, 10))
    second = tab.months.band_at(date(2026, 9, 21))
    assert first is not None and first.key == draft.id and first.label == "v1"
    assert second is not None and second.key == ship.id
    assert [first.color.name(), second.color.name()] == shades(PALETTES[0], 2)
    assert "v1 lands" in tab.months.day_tooltip(date(2026, 9, 16))
    assert "v2, working day 2 of 6" in tab.months.day_tooltip(date(2026, 9, 17))
    assert "v2 lands" in tab.months.day_tooltip(date(2026, 9, 23))


def test_dating_a_milestone_starts_from_the_day_the_sequence_gave_it(services, staged):
    """A milestone's Begins cell shows the day the sequence begins it, quieter than a day of
    its own; typing a day there gives it one, and Begin When the Previous Lands hands the
    decision back. Both undo — and the landing date on the same row answers each edit."""
    tab = services.tabs.open("time", staged.id)
    _read, _draft, _docs, ship = staged.steps
    begins = _cell(tab, _row(tab, ship.id), BEGINS_COLUMN)
    assert begins.text() == "16 Sep" and begins.data(MUTED_ROLE) is True
    assert begins.flags() & Qt.ItemFlag.ItemIsEditable
    _begin(tab, ship.id, date(2026, 10, 5))
    assert ship.module_data[MODULE_ID] == {"start": "2026-10-05", "format": 2}
    assert _landings(tab)[2] == ("v2", "9 October", "5d")
    assert _cell(tab, _row(tab, ship.id), BEGINS_COLUMN).data(MUTED_ROLE) is False
    tab.milestones.selectRow(_row(tab, ship.id))
    assert tab.begin_action.isEnabled()
    tab.begin_action.trigger()
    assert MODULE_ID not in ship.module_data
    assert _landings(tab)[2] == ("v2", "23 September", "6d")
    assert not tab.begin_action.isEnabled()  # Greyed, with the reason in its words.
    assert tab.begin_action.text().endswith("it already does")
    services.undo.undo()  # a burst of edits to one milestone is one step, like typing
    assert MODULE_ID not in ship.module_data
    services.undo.redo()
    assert MODULE_ID not in ship.module_data


def test_the_project_start_is_the_leading_row_of_the_table(services, staged, project):
    """The table leads with the whole plan, and what it begins on is the project's own
    start — always dated, never handed back — and setting it is the calendar click's twin:
    one undoable write of the same entry."""
    tab = services.tabs.open("time", staged.id)
    assert tab.milestones.key_at(0) == ALL_KEY and _cell(tab, 0, 0).text() == ALL_LABEL
    begins = _cell(tab, 0, BEGINS_COLUMN)
    assert begins.data(VALUE_ROLE) == date(2026, 9, 7) and begins.data(MUTED_ROLE) is False
    assert begins.flags() & Qt.ItemFlag.ItemIsEditable
    _begin(tab, ALL_KEY, date(2026, 9, 14))
    assert project.module_data[ESTIMATION_ID]["start"] == "2026-09-14"
    assert tab.months.span[0] == date(2026, 9, 14)
    services.undo.undo()
    assert _cell(tab, 0, BEGINS_COLUMN).data(VALUE_ROLE) == date(2026, 9, 7)


def test_a_date_the_sequence_cannot_keep_is_pushed_and_flagged(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, _draft, _docs, ship = staged.steps
    _begin(tab, ship.id, date(2026, 9, 10))
    lands = _cell(tab, _row(tab, ship.id), LANDS_COLUMN)
    assert lands.text() == "⚠ 23 September"
    assert "Asked to begin 10 September" in lands.toolTip()


def test_a_chosen_colour_overrides_the_dealt_one_until_automatic(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    tab.pick_colour(draft.id, "#C98500")
    assert draft.module_data[MODULE_ID] == {"color": "#c98500", "format": 2}
    assert _cell(tab, _row(tab, draft.id), 0).data(COLOR_ROLE) == "#c98500"
    assert tab.months.band_at(date(2026, 9, 10)).color.name() == "#c98500"
    # The other is still dealt in turn — its shade is its place among two, not one.
    assert _cell(tab, _row(tab, ship.id), 0).data(COLOR_ROLE) == shades(PALETTES[0], 2)[1]
    tab.pick_colour(draft.id, None)
    assert MODULE_ID not in draft.module_data


def test_a_dated_milestone_keeps_its_colour_and_vice_versa(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, _ship = staged.steps
    tab.pick_colour(draft.id, "#c98500")
    tab.milestones.start_changed.emit(draft.id, date(2026, 9, 1))
    assert draft.module_data[MODULE_ID] == {
        "start": "2026-09-01",
        "color": "#c98500",
        "format": 2,
    }
    tab.pick_colour(draft.id, None)
    assert draft.module_data[MODULE_ID] == {"start": "2026-09-01", "format": 2}


def test_picking_a_milestone_emphasises_it_in_the_calendar_and_the_plots(services, staged):
    """A pick highlights; it hides nothing. *All milestones* shows them all alike again."""
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    tab.milestones.selectRow(_row(tab, ship.id))
    assert tab.picked == ship.id
    assert tab.months.emphasised == ship.id
    assert tab.chart._data.emphasis == ship.id
    assert tab.milestones.picked_key() == ship.id
    assert [s.key for s in tab.chart._data.segments] == [draft.id, ship.id]  # both stay
    tab.milestones.selectRow(0)
    assert tab.picked is None and tab.months.emphasised is None
    assert tab.chart._data.emphasis is None and tab.milestones.picked_key() == ALL_KEY
    tab.milestones.selectRow(_row(tab, draft.id))
    assert tab.picked == draft.id
    services.undo.push(SetModuleDataCommand(draft.id, MILESTONE_ID, {}))  # no longer one
    assert tab.picked is None


def test_removing_a_milestone_step_takes_its_row_with_it(services, staged):
    tab = services.tabs.open("time", staged.id)
    _read, draft, _docs, ship = staged.steps
    services.undo.push(RemoveNodeCommand(ship.id))
    assert tab.milestones.keys == (draft.id,)
    assert [label for label, _when, _days in _landings(tab)] == [
        "All milestones",
        "v1",
        "Remaining work",
    ]


def test_the_rows_follow_the_sequence_when_the_graph_reorders_it(services, staged):
    tab = services.tabs.open("time", staged.id)
    read, draft, _docs, ship = staged.steps
    assert tab.milestones.keys == (draft.id, ship.id)
    # Ship now precedes draft in the graph, so its row moves up — and keys says so.
    services.undo.push(SetEdgesCommand(ship.id, "requires", [read.id]))
    services.undo.push(SetEdgesCommand(draft.id, "requires", [ship.id]))
    assert tab.milestones.keys == (ship.id, draft.id)


def test_the_list_scrolls_under_the_staffing_grid(services, staged, app):
    """A plan with more milestones than the panel is tall scrolls its list; the grid the
    whole page answers stays where it is, because scrolling the page away with it would
    take the question off the screen exactly when the answers are being compared."""
    library = services.document
    for index in range(12):
        step = Step(title=f"Ship {index}")
        AddNodeCommand(staged.id, step).redo(library)
        SetModuleDataCommand(step.id, ESTIMATION_ID, write_days(1.0)).redo(library)
        SetModuleDataCommand(step.id, MILESTONE_ID, write_milestone_label(f"m{index}")).redo(
            library
        )
    tab = services.tabs.open("time", staged.id)
    window = services.window
    window.resize(1100, 620)
    window.show()
    app.processEvents()
    assert tab.milestones.verticalScrollBar().maximum() > 0  # there is more than fits
    assert tab.matrix.visibleRegion().boundingRect().height() == tab.matrix.height()
    window.hide()


def test_without_milestones_the_table_says_where_to_make_one(tab, project):
    """The one row there is leads the table, so it is what carries the project's start —
    and the note under it says how to add a milestone."""
    assert tab.no_milestones.isVisibleTo(tab.widget)
    assert "Step ▸ Type ▸ Milestone" in tab.no_milestones.text()
    assert tab.milestones.rowCount() == 1 and tab.milestones.key_at(0) == ""
    assert _cell(tab, 0, 0).text() == "All work"
    begins = _cell(tab, 0, BEGINS_COLUMN)
    assert begins.data(VALUE_ROLE) == date(2026, 9, 7)
    assert begins.flags() & Qt.ItemFlag.ItemIsEditable
    _begin(tab, "", date(2026, 9, 14))
    assert project.module_data[ESTIMATION_ID]["start"] == "2026-09-14"


# -- what breaks, said plainly ---------------------------------------------------------------


def test_a_loop_in_the_file_says_which_steps_wait_on_each_other(services, project, tab):
    """The model refuses a cycle; a file does not. Write one behind its back."""
    library = services.document
    read, draft, _docs = project.steps
    read.edges["requires"] = [draft.id]
    library.edges_changed.emit(read.id, None)
    assert not tab.months.isVisibleTo(tab.widget)
    assert not tab.matrix.isVisibleTo(tab.widget)
    assert not tab.chart.isVisibleTo(tab.widget)
    assert tab.banner.isVisibleTo(tab.widget) and not tab.banner.button.isVisibleTo(tab.widget)
    assert "Read the spec, Draft the model" in tab.banner.note.words()
    assert "Unlink one" in tab.banner.note.words() and tab.banner.note.tone() == "error"
    read.edges["requires"] = []
    library.edges_changed.emit(read.id, None)
    assert tab.months.isVisibleTo(tab.widget)
    assert tab.landing == date(2026, 9, 16)


def test_a_stepless_project_says_so_instead_of_a_grid_of_zeros(services, make_project):
    empty = make_project("Empty")
    tab = services.tabs.open("time", empty.id)
    assert tab.empty.isVisibleTo(tab.widget) and tab.empty.text() == NO_STEPS
    assert not tab.split.isVisibleTo(tab.widget)  # no grid, no table, no calendar
    assert tab.controls.isVisibleTo(tab.widget)  # the strip is chrome, and stays


def test_the_tab_titles_itself_after_the_project(tab):
    assert tab.title == "Discovery — Time Estimates"


# -- the team, and progress against the plan -------------------------------------------------


def test_clicking_a_tile_stores_the_team_and_the_tab_restores_it(services, project, tab):
    """The team is the project's staffing assumption, the focus factor's twin: one
    undoable write, and a tab opened later selects it."""
    tab.matrix.select(2, 3)
    assert project.module_data[MODULE_ID] == {"team": [2, 3], "format": 2}
    assert services.undo.undo_text() == "Choose Team"
    services.tabs.close_activity(tab)
    again = services.tabs.open("time", project.id)
    assert again.matrix.selection == (2, 3)
    services.undo.undo()
    assert MODULE_ID not in project.module_data
    assert again.matrix.selection == (1, 1)  # the smallest team is the default


def test_a_stored_team_the_collapsed_grid_cannot_show_selects_its_nearest_seat(services, project):
    """Without agent steps the agent columns collapse; a stored 2 + 3 lands on 2 + 1 and
    a click there writes what the grid shows."""
    library = services.document
    _read, _draft, docs = project.steps
    SetModuleDataCommand(docs.id, AGENT_ID, {}).redo(library)
    SetModuleDataCommand(project.id, MODULE_ID, {"team": [2, 3], "format": 1}).redo(library)
    tab = services.tabs.open("time", project.id)
    assert tab.matrix.agent_counts == (1,) and tab.matrix.selection == (2, 1)
    assert project.module_data[MODULE_ID] == {"team": [2, 3], "format": 1}  # a sync is not a click
    tab.matrix.select(3, 1)
    assert project.module_data[MODULE_ID] == {"team": [3, 1], "format": 2}


def test_each_row_says_how_much_of_the_work_through_it_has_landed(services, staged):
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status

    library = services.document
    read, draft, _docs, ship = staged.steps
    tab = services.tabs.open("time", staged.id)
    landed = lambda: [  # noqa: E731 - read twice, after each write
        _cell(tab, row, LANDED_COLUMN).text() for row in range(tab.milestones.rowCount())
    ]
    assert landed() == ["0%", "0%", "0%"]
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    # By estimated days, the one measure: the whole (2 of 7), then v1 (2 of 4), then v2
    # (2 of 7) — everything through its stretch. The count is in the tooltip's words.
    assert landed() == ["29%", "50%", "29%"]
    assert _cell(tab, _row(tab, ship.id), LANDED_COLUMN).toolTip() == (
        "2d of 7d estimated · 1 of 4 steps done"
    )
    SetModuleDataCommand(draft.id, STATUS_ID, write_status("done", today=TODAY)).redo(library)
    assert landed() == ["57%", "100%", "57%"]


def test_the_right_half_is_no_taller_than_its_content(services, staged, tab, app):
    """The right half scrolled over empty space: the calendar's minimum was its height as
    one narrow column — every month stacked — and a resizable scroll area sizes its page
    to the minimum. One row is the least the calendar can need; the rest is asked through
    heightForWidth at the real width."""
    months = tab.months
    assert months.minimumSizeHint().height() < months.heightForWidth(months.minimumWidth())
    window = services.window
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    right = tab.split.widget(1)
    page = right.widget()
    needed = (
        page.heightForWidth(page.width()) if page.hasHeightForWidth() else page.sizeHint().height()
    )
    assert page.height() <= max(right.viewport().height(), needed)


def test_the_plots_show_the_whole_plan_a_page_at_a_time(services, staged):
    """The plots are always the whole project, by estimated days; a pick changes what is
    held in full ink, never what is drawn; the toggles over them turn the page, and the
    Volume page reads the recorded days."""
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status

    read, draft, _docs, ship = staged.steps
    tab = services.tabs.open("time", staged.id)
    # The spec is read the Friday before the plan starts: the rest resumes on the Monday.
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    data = tab.chart._data
    assert data.finish == date(2026, 9, 17) and data.emphasis is None
    assert data.expected[0] == (TODAY, 0.0)
    assert data.expected[-1] == (date(2026, 9, 17), 1.0)
    assert data.actual[-1] == (TODAY, pytest.approx(2 / 7))
    assert [(s.key, s.label, s.now) for s in data.segments] == [
        (draft.id, "v1", (TODAY, date(2026, 9, 10))),
        (ship.id, "v2", (date(2026, 9, 10), date(2026, 9, 17))),
    ]
    assert [s.color.name() for s in data.segments] == shades(PALETTES[0], 2)
    tab.milestones.selectRow(_row(tab, draft.id))
    data = tab.chart._data
    assert data.emphasis == draft.id and data.emphasised is data.segments[0]
    assert data.finish == date(2026, 9, 17) and len(data.segments) == 2  # nothing hidden
    assert "plan now:" in tab.chart.tooltip_at(date(2026, 9, 10))
    assert "actual: 29% of days" in tab.chart.tooltip_at(TODAY)
    assert tab.chart.tooltip_at(date(2026, 9, 16)).startswith("16 September")
    assert tab.chart.span[0] <= TODAY and tab.chart.span[1] >= date(2026, 9, 17)
    # The pages: Progress is what the tab opens on; the others are a click away.
    assert tab.page == "progress"
    assert [panel.kind for panel in tab.chart.panels()] == ["status", "scope"]
    tab.page_buttons["shift"].click()
    assert tab.page == "shift" and [p.kind for p in tab.chart.panels()] == ["shift"]
    tab.page_buttons["volume"].click()
    assert [p.kind for p in tab.chart.panels()] == ["volume", "remaining"]
    # The recorder wrote today's row when the tab opened and again after the status: one
    # day, the live reading — 7d of scope, 5d of it still ahead.
    assert data.volume[-1] == (TODAY, 7.0) and data.remaining[-1] == (TODAY, 5.0)
    assert "scope: 7d" in tab.chart.tooltip_at(TODAY, "volume")


def test_the_recorder_writes_the_day_once_off_the_undo_stack(services, staged):
    """A settled change records the day's row — once, replaced within the day, never
    when nothing changed — and Ctrl+Z undoes the status, not the record."""
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status
    from dplanner.modules.time_estimates.progress import HISTORY_ID, read_history

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
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status
    from dplanner.modules.time_estimates.progress import read_history

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
    from dplanner.modules.time_estimates.progress import read_history

    SetModuleDataCommand(project.id, ESTIMATION_ID, write_start(None)).redo(services.document)
    landing = tab.landing
    assert tab.snapshot().day == TODAY and read_history(project)[-1].day == TODAY
    monday = date(2026, 9, 7)
    services.clock.pin(monday)
    # Eight working days from Friday the 4th land on the 15th; from the Monday, a day later.
    assert landing == date(2026, 9, 15) and tab.landing == date(2026, 9, 16)
    assert tab.snapshot().day == monday
    assert [row.day for row in read_history(project)] == [TODAY, monday]


def test_the_plots_open_in_a_window_of_their_own_and_follow_the_plan(
    services, staged, tab, monkeypatch
):
    """⤢ opens every page of the plots with the same record, and a change made while the
    window is open reaches both charts — one ``ChartData``, two views of it."""
    from dplanner.modules.time_estimates.chart import ALL_PAGES, ChartDialog

    seen = []

    def fake_exec(dialog):
        assert dialog.chart.page == ALL_PAGES
        seen.append((dialog.chart._data, dialog.windowTitle()))
        ship = staged.steps[-1]
        services.undo.push(SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(9.0)))
        seen.append((dialog.chart._data, tab.chart._data))
        return 0

    monkeypatch.setattr(ChartDialog, "exec", fake_exec)
    tab.expand.click()
    (opened, title), (expanded, inline) = seen
    assert opened is not None and title == tab.title
    assert expanded is inline and expanded is not opened  # both redrew, from one record
    assert tab._expanded is None  # closing it leaves nothing behind


def _old_plan(draft_id, ship_id, day):
    from dplanner.modules.time_estimates.progress import Landing, Snapshot, Stretch, Tally

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


def test_the_plots_compare_the_two_snapshots_the_strip_names(services, staged):
    """The then side reads the plan at the project's start unless picked otherwise — a
    day, a saved snapshot — and the picker's tooltip names the record that stood in, so
    the comparison is never a guess; the milestone rows say in words which way each
    landing went against that plan."""
    from dplanner.modules.time_estimates.progress import (
        HISTORY_ID,
        Pick,
        write_history,
    )

    library = services.document
    _read, draft, _docs, ship = staged.steps
    old = _old_plan(draft.id, ship.id, date(2026, 9, 1))
    SetModuleDataCommand(staged.id, HISTORY_ID, write_history([old])).redo(library)
    tab = services.tabs.open("time", staged.id)
    assert tab.then_pick.kind == "start" and tab.now_pick.kind == "now"
    assert tab.then_picker.text() == "Plan at start" and tab.now_picker.text() == "Now"
    # The start is the 7th; the record that stands in for it is the 1st's, and it says so.
    assert tab.then_picker.toolTip() == "the plan at start, recorded 1 September"
    assert tab.now_picker.toolTip() == "the plan now"
    assert not tab.controls.is_shown(tab.then_day)
    data = tab.chart._data
    assert data.basis == "the plan at start, recorded 1 September" and data.as_of == ""
    assert data.baseline_finish == date(2026, 9, 18) and data.finish == date(2026, 9, 23)
    assert data.baseline[0] == (date(2026, 9, 7), 0.0) and data.baseline[-1] == (
        date(2026, 9, 18),
        1.0,
    )
    assert [(s.then, s.now) for s in data.segments] == [
        ((date(2026, 9, 7), date(2026, 9, 14)), (date(2026, 9, 7), date(2026, 9, 16))),
        ((date(2026, 9, 15), date(2026, 9, 18)), (date(2026, 9, 16), date(2026, 9, 23))),
    ]
    assert segment_words(data.segments[1], data.basis, data.today) == (
        "v2 lands 23 September — 3 working days later than the plan at start, "
        "recorded 1 September said (18 September)"
    )
    assert tab.chart.title(tab.chart.panel("scope")) == (
        "Scope change — versus the plan at start, recorded 1 September"
    )
    assert "the plan at start, recorded 1 September: " in tab.chart.tooltip_at(
        date(2026, 9, 10), "scope"
    )
    assert "plan now" in tab.chart.tooltip_at(date(2026, 9, 10), "scope")
    assert "plan at" not in tab.chart.tooltip_at(date(2026, 9, 10))  # the status plot's words
    # Day…: the field appears beside the picker, and the pick follows it.
    tab.then_picker.picked.emit(Pick("day", day=date(2026, 9, 3)))
    assert tab.then_pick == Pick("day", day=date(2026, 9, 3))
    assert tab.controls.is_shown(tab.then_day) and tab.then_picker.text() == "3 September"
    assert tab.then_picker.toolTip() == "the plan at 3 September, recorded 1 September"
    # After every record: never today's own, which is the plan now — the 1st's, and said.
    tab.then_day.setDate(QDate(2030, 1, 1))
    data = tab.chart._data
    assert tab.then_pick.day == date(2030, 1, 1) and data.compared
    assert segment_words(data.segments[1], data.basis, data.today) == (
        "v2 lands 23 September — 3 working days later than the plan at 1 Jan '30, "
        "recorded 1 September said (18 September)"
    )
    tab.then_picker.picked.emit(Pick("start"))
    assert tab.then_pick.kind == "start" and not tab.controls.is_shown(tab.then_day)
    assert tab.then_picker.menu_labels() == ["Plan at start", "Day…"]  # nothing saved yet


def test_a_snapshot_saved_on_purpose_is_named_kept_and_compared_against(services, staged):
    """Save snapshot… keeps the plan as it stands under a title — one undoable write that
    leaves the recorder's day alone — and both pickers then offer it: as the then side it
    is what the plots compare against, as the now side the plots read the plan as of it.
    Forgetting it takes it out of the menus; a now side that read it goes back to live."""
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status
    from dplanner.modules.time_estimates.progress import (
        HISTORY_ID,
        Pick,
        read_history,
        read_saved,
    )
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
    assert tab.chart._data.marks == ((TODAY, "Kickoff review"),)
    # A taken title is refused in the dialog, with the reason under the field.
    again = SaveSnapshotDialog(["Kickoff review"], tab.widget)
    again.title.setText("kickoff review")
    assert not _primary(again).isEnabled()
    assert "already saved" in again.reason.words() and again.reason.tone() == "error"
    again.deleteLater()
    # Both pickers offer it, dated.
    assert tab.then_picker.menu_labels()[1].startswith("Kickoff review · ")
    assert tab.now_picker.menu_labels()[:2] == ["Now", tab.then_picker.menu_labels()[1]]
    # Work lands and the plan grows; the saved snapshot is what the plots compare against.
    services.undo.push(SetModuleDataCommand(read.id, STATUS_ID, write_status("done", today=TODAY)))
    services.undo.push(SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(4.0)))
    tab.then_picker.picked.emit(Pick("saved", title="Kickoff review"))
    data = tab.chart._data
    assert tab.then_picker.text() == "Kickoff review"
    assert data.basis == f"Kickoff review ({format_date(TODAY, TODAY)})"
    # The spec, read before the plan began, saved the four days that two more of shipping cost.
    assert data.baseline_finish == date(2026, 9, 23) and data.finish == date(2026, 9, 23)
    assert data.volume[-1] == (TODAY, 9.0) and data.remaining[-1] == (TODAY, 7.0)
    # As the now side, the plots read the plan as of it: nothing done, 7d of scope.
    tab.then_picker.picked.emit(Pick("start"))
    tab.now_picker.picked.emit(Pick("saved", title="Kickoff review"))
    data = tab.chart._data
    assert data.as_of == f"Kickoff review ({format_date(TODAY, TODAY)})"
    assert data.finish == date(2026, 9, 23) and data.actual[-1] == (TODAY, 0.0)
    assert tab.chart.title(tab.chart.panel("status")) == f"Progress — as of {data.as_of}"
    assert data.volume[-1] == (TODAY, 7.0)
    # Forgetting it is undoable too, and the now side falls back to the live plan.
    tab.now_picker.forget.emit("Kickoff review")
    assert services.undo.undo_text().endswith("Forget Snapshot")
    assert read_saved(staged) == [] and tab.now_pick.kind == "now"
    assert tab.chart._data.finish == date(2026, 9, 23) and tab.chart._data.marks == ()
    services.undo.undo()
    assert [row.title for row in read_saved(staged)] == ["Kickoff review"]
    assert staged.module_data[HISTORY_ID]["format"] == 3
    before = services.undo.undo_text()
    tab.now_picker.forget.emit("nobody")  # nothing to forget: nothing pushed
    assert services.undo.undo_text() == before


def test_the_strip_says_updating_until_the_page_has(services, staged, tab):
    """A change arrives, the page waits for the burst to settle, and the strip says so
    in between — and stops saying so the moment the report has re-run.

    The indicator follows the debouncer itself (``pending_changed``), so this holds for a
    rebuild that raises as much as one that returns; the pair of statements the old
    hand-shown label needed could only ever be right by inspection.
    """
    services.debounce.set_immediate(False)
    try:
        assert tab.updating.isHidden()
        ship = staged.steps[-1]
        services.undo.push(SetModuleDataCommand(ship.id, ESTIMATION_ID, write_days(9.0)))
        assert not tab.updating.isHidden()
        services.debounce.flush_all()
        assert tab.updating.isHidden()
        assert tab.chart._data.finish == date(2026, 10, 13)
    finally:
        services.debounce.set_immediate(True)


def test_the_milestone_plot_rows_the_milestones_and_a_gap_the_plan_leaves_empty_is_dotted(
    services, staged, tab
):
    """v1 and v2 get a row each where they land; giving v2 a start date a week past v1's
    landing leaves the days between empty, and the plots say so."""
    from dplanner.modules.time_estimates.schedule import MODULE_ID as TIME_ID
    from dplanner.modules.time_estimates.schedule import write_milestone

    data = tab.chart._data
    assert [(s.label, s.now[1]) for s in data.milestones] == [
        ("v1", date(2026, 9, 16)),
        ("v2", date(2026, 9, 23)),
    ]
    assert [panel.kind for panel in tab.chart.panels()] == ["status", "scope"]
    tab.page_buttons["shift"].click()
    assert [panel.kind for panel in tab.chart.panels()] == ["shift"]
    assert data.idle == ()
    ship = staged.steps[3]
    services.undo.push(
        SetModuleDataCommand(ship.id, TIME_ID, write_milestone(date(2026, 9, 24), None))
    )
    data = tab.chart._data
    assert data.idle == ((date(2026, 9, 16), date(2026, 9, 24)),)
    assert "no work planned" in tab.chart.tooltip_at(date(2026, 9, 21))
