"""Wave view on the canvas: the same graph, every card in the column of its dependency depth.

What Wave view must keep doing: toggling it writes nothing — the plan stays byte-identical —
and the cards it moves are the same items, at seats ``sorts.arranged_in_waves`` derives on
every sync; *Keep This Arrangement* is its one way to the store, as one undo step; and no
hand moves a card whose seat is derived.
"""

from datetime import date

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsItem
from tests.domain.test_store import fingerprint
from tests.modules.canvas.test_canvas import (
    centre_of,
    drag,
    press_key,
    save_layout,
    scene,
    silence_details,
    view,
)

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.canvas.keymap import bound_actions
from dplanner.modules.canvas.layouts.placement import positions
from dplanner.modules.canvas.layouts.positions import (
    GRID,
    MODULE_ID,
    NODE_H,
    NODE_W,
    default_size,
    snapped,
    write_member,
    write_position,
)
from dplanner.modules.canvas.layouts.sorts import EN_DASH, arranged_in_waves, waves
from dplanner.modules.canvas.layouts.verbs import wave_view
from dplanner.planning.estimate import MODULE_ID as ESTIMATE_ID
from dplanner.planning.estimate import write as estimate
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import Status
from dplanner.planning.status import write as status

# Where each step was put by hand, on the grid: nowhere near its wave, so a move shows.
HAND = {
    "Kick-off": (40.0, 600.0),
    "Model": (40.0, 40.0),
    "Screens": (704.0, 40.0),
    "Ship": (400.0, 400.0),
}


@pytest.fixture
def plan(services, make_project):
    """Kick-off → Model → Ship, and Kick-off → Screens, every card placed by hand."""
    project = make_project("Discovery")
    steps = {title: Step(title=title) for title in HAND}
    for step in steps.values():
        services.undo.push(AddNodeCommand(project.id, step))
        services.undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write_position(*HAND[step.title]))
        )
    for waiter, source in (("Model", "Kick-off"), ("Screens", "Kick-off"), ("Ship", "Model")):
        services.undo.push(SetEdgesCommand(steps[waiter].id, "requires", [steps[source].id]))
    services.undo.break_coalescing()
    services.autosave.flush_now()
    return project, steps


@pytest.fixture
def tab(services, plan):
    return services.tabs.open("project", plan[0].id)


def seats(tab):
    return {
        step_id: (item.pos().x(), item.pos().y()) for step_id, item in scene(tab)._nodes.items()
    }


def derived(services, project):
    return waves(services.document, project, default_size)


def on_grid(placed):
    """Seats as the canvas shows them: snapped, as every seat it is handed is."""
    return {s: (snapped(x, GRID), snapped(y, GRID)) for s, (x, y) in placed.items()}


def test_toggling_wave_view_on_and_off_leaves_the_plan_byte_identical(
    services, library_repo, plan, tab
):
    before = fingerprint(library_repo)
    undo = services.undo.undo_text()
    tab.run_action("canvas.waves")
    assert wave_view(plan[0].id)
    tab.run_action("canvas.waves")
    assert not wave_view(plan[0].id)
    assert not services.autosave.has_pending()
    services.autosave.flush_now()
    assert fingerprint(library_repo) == before
    assert services.undo.undo_text() == undo  # Nothing reached the undo stack either.


def test_wave_view_moves_the_same_cards_to_the_derived_seats_and_back(services, plan, tab):
    project, _steps = plan
    items = dict(scene(tab)._nodes)
    free = seats(tab)
    tab.run_action("canvas.waves")
    assert seats(tab) == derived(services, project)
    assert scene(tab)._nodes == items  # Moved by the diff sync, never rebuilt.
    tab.run_action("canvas.waves")
    assert seats(tab) == free == positions(services.document, project)


def test_every_card_in_wave_view_wears_the_default_size(services, plan, tab):
    _project, steps = plan
    services.undo.push(
        SetModuleDataCommand(steps["Model"].id, MODULE_ID, write_position(40, 40, (400.0, 200.0)))
    )
    tab.run_action("canvas.waves")
    assert scene(tab).node(steps["Model"].id).size() == (NODE_W, NODE_H)
    tab.run_action("canvas.waves")
    assert scene(tab).node(steps["Model"].id).size() == (400.0, 200.0)


def test_keep_this_arrangement_is_one_undo_and_ends_in_free_view(services, plan, tab):
    project, _steps = plan
    free = seats(tab)
    tab.run_action("canvas.waves")
    shown = seats(tab)
    tab.run_action("canvas.waves_keep")
    assert services.undo.undo_text() == "Keep Wave Arrangement"
    assert not wave_view(project.id)
    assert seats(tab) == shown == positions(services.document, project)
    services.undo.undo()
    assert seats(tab) == free
    assert not wave_view(project.id)  # Undo puts the seats back, and stays in Free view.


def test_keep_is_greyed_outside_wave_view(services, plan, tab):
    state = services.actions.spec("canvas.waves_keep").state(services.context.current())
    assert not state.enabled and "not in Wave view" in (state.label or "")


def test_a_sort_or_a_named_layout_leaves_wave_view_first(services, plan, tab):
    project, _steps = plan
    save_layout(services, project, "by hand")
    tab.run_action("canvas.waves")
    tab.run_action("canvas.sort_spine")
    assert not wave_view(project.id)
    assert seats(tab) == on_grid(positions(services.document, project))
    tab.run_action("canvas.waves")
    tab._layout_verbs.apply(project.id, "by hand")
    assert not wave_view(project.id)
    assert seats(tab) == {step.id: HAND[step.title] for step in project.steps}


def test_the_picker_reads_waves_and_the_switch_follows(services, plan, tab):
    project, _steps = plan
    save_layout(services, project, "by hand")
    tab.run_action("canvas.waves")
    assert tab._layout_button.text() == "Waves"
    assert tab._view_switch.value() is True
    tab._view_switch.picked.emit(False)  # The switch runs the verb; the verb decides.
    assert not wave_view(project.id)
    assert tab._layout_button.text() == "by hand"
    assert tab._view_switch.value() is False


def test_a_card_in_wave_view_is_picked_but_never_dragged_or_resized(app, services, plan, tab):
    _project, steps = plan
    tab.run_action("canvas.waves")
    model = scene(tab).node(steps["Model"].id)
    assert not model.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    corner = model.scenePos() + QPointF(NODE_W, NODE_H)
    assert model.edge_at(corner) == ""  # No resize band to take hold of.
    before = seats(tab)
    drag(app, tab, centre_of(model), centre_of(model) + QPointF(160, 120))
    assert seats(tab) == before
    assert scene(tab).selection().steps == (steps["Model"].id,)  # Picked all the same.
    assert services.undo.undo_text() != "Move Step"


def test_a_stack_in_wave_view_is_picked_whole_and_moved_by_nobody(app, services, plan, tab):
    _project, steps = plan
    services.undo.push(
        SetModuleDataCommand(steps["Model"].id, MODULE_ID, write_position(40, 40, stack="s1"))
    )
    services.undo.push(SetModuleDataCommand(steps["Ship"].id, MODULE_ID, write_member("s1")))
    tab.run_action("canvas.waves")
    before = seats(tab)
    ship = scene(tab).node(steps["Ship"].id)
    drag(app, tab, centre_of(ship), centre_of(ship) + QPointF(0, 200))
    assert seats(tab) == before
    assert seats(tab)[steps["Model"].id][0] == seats(tab)[steps["Screens"].id][0]


def test_divide_and_contract_are_greyed_in_wave_view(services, plan, tab):
    tab.run_action("canvas.waves")
    for action_id in (
        "canvas.divide_vertical",
        "canvas.divide_horizontal",
        "canvas.contract_vertical",
        "canvas.contract_horizontal",
    ):
        state = services.actions.spec(action_id).state(services.context.current())
        assert not state.enabled and "not in Wave view" in (state.label or ""), action_id


def test_a_step_born_in_wave_view_lands_in_its_wave_picked_and_somewhere_free(
    services, plan, tab, monkeypatch
):
    project, _steps = plan
    opened = silence_details(monkeypatch)
    tab.run_action("canvas.waves")
    scene(tab).create_requested.emit(40.0, 40.0)  # A double-click on a derived seat.
    born = project.steps[-1]
    assert [dialog.panel.current_step_id() for dialog in opened] == [born.id]
    assert scene(tab).selection().steps == (born.id,)
    assert seats(tab)[born.id] == derived(services, project)[born.id]
    stored = positions(services.document, project)
    others = [seat for step_id, seat in stored.items() if step_id != born.id]
    assert stored[born.id] not in others
    assert stored[born.id][0] > max(x for x, _y in others)  # A fresh column, right of all.


def test_a_link_from_elsewhere_moves_only_what_it_changes_the_wave_of(services, plan, tab):
    """Another writer — an agent's ``dplanner step link`` — adds a link while the window is
    in Wave view: the waiter goes to its new wave, everybody else keeps theirs, and no seat
    is written for anyone."""
    project, steps = plan
    tab.run_action("canvas.waves")
    before = seats(tab)
    stored = {step.id: step.module_data.get(MODULE_ID) for step in project.steps}
    services.document.set_edges(
        steps["Screens"].id, "requires", [steps["Kick-off"].id, steps["Model"].id]
    )
    after = seats(tab)
    assert after == derived(services, project)
    changed_wave = {step_id for step_id in before if before[step_id][0] != after[step_id][0]}
    assert changed_wave == {steps["Screens"].id}
    # Ship shares its column with Screens now, and keeps it.
    assert after[steps["Ship"].id][0] == before[steps["Ship"].id][0]
    assert {step.id: step.module_data.get(MODULE_ID) for step in project.steps} == stored


def test_v_on_the_canvas_is_wave_view(app, services, plan, tab):
    assert bound_actions(Qt.Key.Key_V, Qt.KeyboardModifier.NoModifier) == ("canvas.waves",)
    press_key(app, tab, Qt.Key.Key_V)
    assert wave_view(plan[0].id)
    press_key(app, tab, Qt.Key.Key_V)
    assert not wave_view(plan[0].id)


def test_the_ruler_names_each_wave_says_when_it_runs_and_how_much_is_done(services, plan, tab):
    project, steps = plan
    services.undo.push(SetModuleDataCommand(steps["Kick-off"].id, ESTIMATE_ID, estimate(1.0)))
    services.undo.push(SetModuleDataCommand(steps["Model"].id, ESTIMATE_ID, estimate(2.0)))
    services.undo.push(SetModuleDataCommand(steps["Screens"].id, ESTIMATE_ID, estimate(0.5)))
    services.undo.push(
        SetModuleDataCommand(
            steps["Model"].id, STATUS_ID, status(Status.DONE, today=date(2026, 9, 28))
        )
    )
    assert view(tab).ruler.headings() == ()  # Free view has no ruler.
    tab.run_action("canvas.waves")
    said = [(h.label, h.span, h.done) for h in view(tab).ruler.headings()]
    assert said == [
        ("START", f"0 {EN_DASH} 1 d", ""),
        ("WAVE 2", f"1 {EN_DASH} 3 d", "1 of 2 done"),
        ("WAVE 3", "day 3", ""),
    ]
    arrangement = arranged_in_waves(services.document, project, default_size)
    headings = view(tab).ruler.headings()
    assert [h.left for h in headings] == [wave.left for wave in arrangement.waves]
    assert view(tab)._bands  # Every other column carries its faint band.
    tab.run_action("canvas.waves")
    assert view(tab).ruler.headings() == () and not view(tab)._bands
