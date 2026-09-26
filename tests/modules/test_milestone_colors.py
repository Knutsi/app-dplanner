"""One milestone, one colour, wherever it is drawn.

The point of dealing a milestone its shade is that *every* surface says the same thing: a
card on the canvas, a row in the order table, a card on the progression board, a heading in
the Tests tab, a card in the coverage lane, the swatch in the Milestone tab, the band in the
calendar and the graph in the report. Each of those reads a different painter, so the only
thing that can keep them honest is a test that compares them against one another rather than
against a literal — and that is what most of this file does.

The deal itself (the maps, the centred sampling, an override pinning one milestone) is
``tests/modules/test_time_estimates.py``'s; here it is only ever the *source* the surfaces
are checked against.
"""

from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as write_days
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as write_milestone_label
from dplanner.modules.time_estimates.schedule import MODULE_ID as TIME_ID
from dplanner.modules.time_estimates.schedule import (
    milestone_colors,
    read_palette,
    write_milestone,
    write_project,
)
from dplanner.theme.palettes import PALETTES, palette, shades

MAKO = palette("mako")


@pytest.fixture
def project(services, make_project):
    """A chain of work closed by two milestones, dated — the smallest plan with a sequence.

    ``v1`` closes the first two steps and ``v2`` the third, so the two are dealt the first
    and second shade of whatever map the project is on.
    """
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Draft the model", "Ship it"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    read, draft, ship = project.steps
    SetEdgesCommand(draft.id, "requires", [read.id]).redo(library)
    SetEdgesCommand(ship.id, "requires", [draft.id]).redo(library)
    for step in (read, draft, ship):
        SetModuleDataCommand(step.id, ESTIMATION_ID, write_days(2.0)).redo(library)
    SetModuleDataCommand(draft.id, MILESTONE_ID, write_milestone_label("v1")).redo(library)
    SetModuleDataCommand(ship.id, MILESTONE_ID, write_milestone_label("v2")).redo(library)
    SetModuleDataCommand(project.id, ESTIMATION_ID, write_start(date(2026, 9, 7))).redo(library)
    return project


def milestones(project):
    """``(v1, v2)`` — the two milestone steps, in the order the roadmap runs."""
    _read, draft, ship = project.steps
    return draft, ship


def dealt(services, project) -> dict[str, str]:
    return milestone_colors(
        services.document, project, lambda step: bool(step.module_data.get(MILESTONE_ID))
    )


def milestone_section(services, step_id: str):
    """The Milestone tab built through its *registered* factory, which is what tests that
    the composition root actually handed the section its shade seam."""
    found = next(s for s in services.inspector_sections.sections() if s.id == "step_milestone.tab")
    section = found.factory()
    section.show_target(step_id)
    return section


def order_rows(services, project):
    """``{step id: (row tint colour, key badge present)}`` from a built Order tab."""
    from dplanner.modules.step_order.view import COLOR_ROLE, STEP_ROLE, TITLE_COLUMN

    tab = services.tabs.open("order", project.id)
    found = {}
    for row in range(tab.table.rowCount()):
        item = tab.table.item(row, TITLE_COLUMN)
        found[item.data(STEP_ROLE)] = (item.data(COLOR_ROLE) or "", not item.icon().isNull())
    return found


# -- the deal reaches every surface -------------------------------------------------------


def test_the_canvas_the_order_table_and_the_calendar_paint_one_milestone_one_colour(
    services, project
):
    """The whole point, asserted between surfaces rather than against a literal.

    Three painters, three vocabularies — a ``NodeAccent``'s ``tone_color``, a table row's
    ``COLOR_ROLE`` and the Time tab's milestone rows — and one hex behind all of them.
    """
    v1, v2 = milestones(project)
    colors = dealt(services, project)
    assert list(colors.values()) == shades(PALETTES[0], 2)

    canvas = services.tabs.open("project", project.id)
    assert canvas._scene._nodes[v1.id]._accent.tone_color == colors[v1.id]
    assert canvas._scene._nodes[v2.id]._accent.tone_color == colors[v2.id]

    rows = order_rows(services, project)
    assert rows[v1.id][0] == colors[v1.id]
    assert rows[v2.id][0] == colors[v2.id]

    time_tab = services.tabs.open("time", project.id)
    assert [row.named.color for row in time_tab.shifts.rows] == list(colors.values())


def test_a_milestones_row_wears_its_key_as_a_badge_and_a_plain_step_does_not(services, project):
    """DESIGN.md's *Tables*: the key badge stands where the glyph would, in the shade."""
    v1, _v2 = milestones(project)
    read = project.steps[0]
    rows = order_rows(services, project)
    assert rows[v1.id][1] is True
    assert rows[read.id][0] == ""  # A plain step carries no shade at all.


def test_the_coverage_lane_and_the_milestone_tab_read_the_same_deal(services, project):
    """The two surfaces furthest apart in the build agree, which is the interesting pair."""
    from dplanner.modules.coverage.trace import MILESTONES, milestone_token

    v1, v2 = milestones(project)
    colors = dealt(services, project)

    coverage = services.tabs.open("coverage", project.id)
    coverage.view.resize(1000, 400)
    lane = {card.item.id: card.item.color for card in coverage.scene.lane_cards(MILESTONES)}
    assert lane[milestone_token(v1.id)] == colors[v1.id]
    assert lane[milestone_token(v2.id)] == colors[v2.id]

    section = milestone_section(services, v2.id)
    assert section.swatch._color == colors[v2.id]
    assert section.swatch.toolTip() == "2nd of 2 · Viridis"
    section.dispose()


def test_a_third_milestone_re_deals_every_surface_at_once(services, project):
    """Adding one re-deals them all, because the shade *means* place in the sequence."""
    library = services.document
    v1, v2 = milestones(project)
    before = dealt(services, project)
    assert list(before.values()) == shades(PALETTES[0], 2)

    AddNodeCommand(project.id, Step(title="Ship again")).redo(library)
    later = project.steps[-1]
    SetEdgesCommand(later.id, "requires", [v2.id]).redo(library)
    SetModuleDataCommand(later.id, MILESTONE_ID, write_milestone_label("v3")).redo(library)

    after = dealt(services, project)
    assert list(after.values()) == shades(PALETTES[0], 3)
    assert after[v1.id] != before[v1.id]  # every one of them moved
    assert order_rows(services, project)[v1.id][0] == after[v1.id]


def test_a_chosen_colour_wins_everywhere_without_moving_the_others(services, project):
    """An override pins one milestone; the rest keep the places they were dealt."""
    library = services.document
    v1, v2 = milestones(project)
    SetModuleDataCommand(v1.id, TIME_ID, write_milestone(None, "#C98500")).redo(library)

    colors = dealt(services, project)
    assert colors[v1.id] == "#c98500"
    assert colors[v2.id] == shades(PALETTES[0], 2)[1]
    assert order_rows(services, project)[v1.id][0] == "#c98500"


def test_the_stretch_order_and_the_placed_order_are_the_same_sequence(services, project):
    """``phase_colors`` looks a stretch's milestone up in the deal, which assumes the two
    walks agree — they are both the topological order, and this is what says so."""
    time_tab = services.tabs.open("time", project.id)
    colors = dealt(services, project)
    snapshot = time_tab.snapshot()
    assert snapshot is not None
    assert [stretch.key for stretch in snapshot.stretches if stretch.key] == list(colors)


# -- View ▸ Milestone Colours --------------------------------------------------------------


def milestone_menu(services):
    view = next(a.menu() for a in services.window.menuBar().actions() if a.text() == "&View")
    return next(a.menu() for a in view.actions() if a.text() == "Milestone Colours")


def test_the_menu_lists_every_map_and_ticks_the_projects_own(services, project):
    canvas = services.tabs.open("project", project.id)
    assert canvas is not None
    services.context.refresh()

    labels = [a.text() for a in milestone_menu(services).actions() if not a.isSeparator()]
    assert labels == [found.name for found in PALETTES]

    ticked = [a.text() for a in milestone_menu(services).actions() if a.isChecked()]
    assert ticked == ["Viridis"]  # the default, stored or not


def test_picking_a_map_is_one_undoable_write_every_surface_follows(services, project):
    v1, _v2 = milestones(project)
    services.tabs.open("project", project.id)
    services.context.refresh()

    services.actions.run("appearance.milestones.mako", services.context.current())
    assert read_palette(project) is MAKO
    assert project.module_data[TIME_ID] == {"palette": "mako", "format": 2}
    assert dealt(services, project)[v1.id] == shades(MAKO, 2)[0]
    assert order_rows(services, project)[v1.id][0] == shades(MAKO, 2)[0]

    services.undo.undo()
    assert TIME_ID not in project.module_data
    assert dealt(services, project)[v1.id] == shades(PALETTES[0], 2)[0]


def test_the_tick_follows_a_map_changed_from_outside_the_menu(services, project):
    """A terminal's ``dplanner schedule palette``, the Time tab's picker, an undo — the menu
    subscribes to the module entry rather than re-reading a file in a state callback."""
    library = services.document
    services.tabs.open("project", project.id)
    services.context.refresh()

    SetModuleDataCommand(
        project.id, TIME_ID, write_project(project, today=date(2026, 9, 21), palette_id="rocket")
    ).redo(library)
    library.module_data_changed.emit(project.id, TIME_ID, "outside")

    ticked = [a.text() for a in milestone_menu(services).actions() if a.isChecked()]
    assert ticked == ["Rocket"]


def test_with_no_project_the_entries_are_greyed_and_say_why(services):
    """*Hidden means absent; disabled means not now* — the entry teaches its precondition."""
    from dplanner.modules.appearance.module import NO_PROJECT

    services.context.clear_scope("activity")
    services.context.refresh()
    entry = services.window.dynamic_menubar.action("appearance.milestones.viridis")
    assert not entry.isEnabled()
    assert entry.text() == NO_PROJECT
