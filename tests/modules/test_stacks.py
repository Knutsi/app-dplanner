"""A stack is one tall card to everything that reads positions — ``stacks.py`` and every
reader it folds into, with no Qt.

Membership is written directly, the way the stack verbs write it (``stack_helpers.py``):
``"stack"`` on every member's entry and a seat on the first member alone. What is pinned is
the promise the rest of the editor leans on: the members are always a column under the
first member's seat, and no sort, tidy, shift, contract, free spot or named layout can
split one.
"""

import math

import pytest
from tests.modules.stack_helpers import PITCH, link, plan, stack, stacked

from dplanner.core.module_data import migrated
from dplanner.modules.project_editor.geometry import contract, shift
from dplanner.modules.project_editor.named_layouts import (
    apply_layout_commands,
    position_commands,
    resize_command,
    save_layout_command,
    snapshot,
)
from dplanner.modules.project_editor.placement import boxes, free_spot, positions
from dplanner.modules.project_editor.positions import (
    DATA_FORMAT,
    MODULE_ID,
    NODE_H,
    NODE_W,
    read_position,
    read_size,
    read_stack,
    write_member,
    write_position,
)
from dplanner.modules.project_editor.sorts import (
    layered_down,
    layered_flow,
    radial,
    spine,
    tidy,
    timeline,
)
from dplanner.modules.project_editor.stacks import (
    FRAME_PAD,
    broken_reason,
    chain,
    fold,
    frame,
    pack,
    read_stacks,
)


def assert_column(placed, steps, *titles):
    """The members are a column under the first, in chain order, at the gap."""
    x, y = placed[steps[titles[0]].id]
    for index, title in enumerate(titles):
        assert placed[steps[title].id] == (x, y + index * PITCH), title


def assert_clear_of_frame(placed, project, steps, *titles):
    """No other card overlaps the stack's frame."""
    members = {steps[t].id for t in titles}
    fx, fy, fw, fh = frame(
        read_stacks(project.steps)[0], placed[steps[titles[0]].id], lambda _m: (NODE_W, NODE_H)
    )
    for step in project.steps:
        if step.id in members:
            continue
        x, y = placed[step.id]
        apart = x + NODE_W <= fx or fx + fw <= x or y + NODE_H <= fy or fy + fh <= y
        assert apart, f"{step.title} is inside the frame"


# -- membership and order -------------------------------------------------------------------


def test_the_order_is_the_chain_whatever_the_project_order():
    library, project, steps = plan("c", "a", "b")
    link(library, steps, "b", "a")
    link(library, steps, "c", "b")
    stack(library, steps, "c", "a", "b")
    [found] = read_stacks(project.steps)
    assert found.members == (steps["a"].id, steps["b"].id, steps["c"].id)
    assert found.head == steps["a"].id and not found.broken


def test_a_gap_is_named_and_every_member_kept():
    library, project, steps = plan("a", "b", "c")
    link(library, steps, "c", "b")  # b never waits on a
    stack(library, steps, "a", "b", "c")
    [found] = read_stacks(project.steps)
    assert found.members == (steps["a"].id, steps["b"].id, steps["c"].id)
    assert found.gaps == ((steps["a"].id, steps["b"].id),)
    assert broken_reason(found, lambda i: library.step(i).title) == "b does not wait on a"


def test_a_fork_and_a_cycle_keep_every_member():
    fork = {"a": [], "b": ["a"], "c": ["a"]}
    assert chain(["a", "b", "c"], fork.__getitem__) == (("a", "b", "c"), (("b", "c"),))
    cycle = {"a": ["b"], "b": ["a"]}  # only a hand edit can make one
    order, _gaps = chain(["a", "b"], cycle.__getitem__)
    assert sorted(order) == ["a", "b"]


def test_a_key_that_is_not_a_string_is_no_stack():
    library, project, steps = plan("a")
    library.set_module_data(steps["a"].id, MODULE_ID, {"x": 1.0, "y": 2.0, "stack": 7})
    assert read_stack(steps["a"]) == "" and read_stacks(project.steps) == []


# -- positions -------------------------------------------------------------------------------


def test_members_sit_in_a_column_under_the_first_members_seat():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    placed = positions(library, project)
    assert placed[steps["a"].id] == (400.0, 80.0)
    assert_column(placed, steps, "a", "b", "c")
    assert list(placed) == [step.id for step in project.steps]


def test_a_seat_a_member_below_the_first_stored_is_ignored():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    library.set_module_data(steps["b"].id, MODULE_ID, write_position(0.0, 0.0, stack="s1"))
    assert positions(library, project)[steps["b"].id] == (400.0, 80.0 + PITCH)


def test_a_stack_whose_first_has_no_seat_stands_in_the_ambient_layout():
    library, project, steps = stacked()
    placed = positions(library, project)
    assert_column(placed, steps, "a", "b", "c")
    assert placed == layered_flow(library, project)


def test_a_settled_plan_with_a_stack_never_computes_the_ambient_layout(monkeypatch):
    library, project, steps = stacked()
    for index, step in enumerate(project.steps):
        if read_stack(step) == "":
            library.set_module_data(step.id, MODULE_ID, write_position(index * 300.0, 0.0))
    stack(library, steps, "a", "b", "c", seat=(300.0, 200.0))

    def fail(*_args):
        raise AssertionError("the ambient layout ran for a settled plan")

    monkeypatch.setattr("dplanner.modules.project_editor.placement.auto_positions", fail)
    assert positions(library, project)[steps["c"].id] == (300.0, 200.0 + 2 * PITCH)


def test_a_stack_of_one_is_still_framed():
    library, project, steps = plan("a")
    stack(library, steps, "a", seat=(40.0, 40.0))
    assert pack(project).sizes[steps["a"].id] == (NODE_W + 2 * FRAME_PAD, NODE_H + 2 * FRAME_PAD)


def test_the_frame_is_as_wide_as_the_widest_member():
    library, project, steps = plan("a", "b")
    link(library, steps, "b", "a")
    library.set_module_data(steps["a"].id, MODULE_ID, write_position(0.0, 0.0, stack="s1"))
    library.set_module_data(steps["b"].id, MODULE_ID, write_member("s1", (320.0, 120.0)))
    [found] = read_stacks(project.steps)
    sizes = {step.id: read_size(step) or (NODE_W, NODE_H) for step in project.steps}
    assert frame(found, (0.0, 0.0), sizes.__getitem__) == (
        -FRAME_PAD,
        -FRAME_PAD,
        320.0 + 2 * FRAME_PAD,
        PITCH + 120.0 + 2 * FRAME_PAD,
    )


# -- the fold --------------------------------------------------------------------------------


def test_the_fold_points_every_dependent_at_the_block():
    _library, project, steps = stacked()
    folded = fold(project)
    by_id = {step.id: step for step in folded.project.steps}
    assert steps["b"].id not in by_id and steps["c"].id not in by_id
    assert by_id[steps["a"].id].edges["requires"] == [steps["start"].id]
    assert by_id[steps["after"].id].edges["requires"] == [steps["a"].id]
    assert all(not step.module_data for step in folded.project.steps)


def test_a_plan_with_no_stack_folds_to_itself():
    _library, project, _steps = plan("a", "b")
    assert fold(project).project is project


# -- every arrangement -----------------------------------------------------------------------


def every_sort(library, project):
    return {
        "flow": layered_flow(library, project),
        "down": layered_down(library, project),
        "spine": spine(library, project),
        "timeline": timeline(library, project),
        "radial": radial(library, project),
    }


def test_every_sort_arranges_a_stack_as_one_block():
    library, project, steps = stacked()
    for name, placed in every_sort(library, project).items():
        assert placed.keys() == {step.id for step in project.steps}, name
        assert_column(placed, steps, "a", "b", "c")
        assert_clear_of_frame(placed, project, steps, "a", "b", "c")


def test_what_follows_a_stack_takes_its_depth_from_the_stack():
    library, project, steps = stacked()
    placed = layered_flow(library, project)
    assert placed[steps["after"].id][0] > placed[steps["a"].id][0]
    # Two columns past start, not four: the stack is one node in the flow.
    assert placed[steps["after"].id][0] - placed[steps["start"].id][0] < 3 * (NODE_W + 80.0)


def test_a_timeline_gives_a_stack_its_members_days_together():
    library, project, steps = stacked()
    placed = timeline(library, project, days_for=lambda _step: 1.0)
    # start is one day, the stack three: after starts four days in.
    assert placed[steps["after"].id][0] - placed[steps["start"].id][0] == 4 * 60.0


def test_a_broken_stack_that_folds_into_a_cycle_still_sorts():
    library, project, steps = plan("x", "a", "b")
    link(library, steps, "a", "x")
    link(library, steps, "x", "b")  # b never waits on a, so the stack is broken
    stack(library, steps, "a", "b")
    for name, placed in every_sort(library, project).items():
        assert placed.keys() == {step.id for step in project.steps}, name
        assert_column(placed, steps, "a", "b")


def test_radial_centred_on_a_member_centres_the_stack():
    library, project, steps = stacked()
    placed = radial(library, project, center=steps["b"].id)
    assert_column(placed, steps, "a", "b", "c")


def test_tidy_keeps_a_stack_whole_and_is_idempotent():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(333.0, 71.0))
    tidied = tidy(project, positions(library, project))
    assert_column(tidied, steps, "a", "b", "c")
    for command in position_commands(project, tidied, "Tidy"):
        command.redo(library)
    assert tidy(project, positions(library, project)) == tidied


@pytest.mark.parametrize("by", [120.0, -120.0])
def test_a_cut_through_a_stack_moves_it_whole(by):
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    packing = pack(project)
    placed = packing.blocks(positions(library, project))
    # A level cut between b's bottom and c's top: the stack's frame centre decides its side.
    cut = (80.0 + PITCH + NODE_H + 80.0 + 2 * PITCH) / 2
    moved = packing.unfold(shift(placed, packing.sizes, "y", cut, by))
    members = {steps[t].id for t in ("a", "b", "c")}
    assert members <= moved.keys() or not members & moved.keys()
    assert_column({**positions(library, project), **moved}, steps, "a", "b", "c")


def test_a_contract_pulls_a_stack_whole():
    library, project, steps = plan("left", "a", "b")
    link(library, steps, "b", "a")
    library.set_module_data(steps["left"].id, MODULE_ID, write_position(40.0, 80.0))
    stack(library, steps, "a", "b", seat=(1000.0, 80.0))
    packing = pack(project)
    placed = packing.blocks(positions(library, project))
    done = contract(placed, packing.sizes, "x", 600.0, -math.inf)
    moved = packing.unfold(done.moved)
    assert moved.keys() == {steps["a"].id, steps["b"].id}
    assert_column(moved, steps, "a", "b")
    frame_left = moved[steps["a"].id][0] - FRAME_PAD
    assert frame_left >= 40.0 + NODE_W + 80.0  # one gap short of the card it closed on


# -- writing ---------------------------------------------------------------------------------


def test_moving_any_member_moves_the_stack_through_its_first():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    [command] = position_commands(project, {steps["b"].id: (600.0, 300.0)}, "Move Step")
    command.redo(library)
    assert read_position(steps["a"]) == (600.0, 300.0 - PITCH)
    assert read_stack(steps["a"]) == "s1"
    assert read_position(steps["b"]) is None and read_stack(steps["b"]) == "s1"


def test_the_first_members_own_seat_wins():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    placed = {steps["c"].id: (0.0, 0.0), steps["a"].id: (40.0, 40.0)}
    for command in position_commands(project, placed, "Move Steps"):
        command.redo(library)
    assert read_position(steps["a"]) == (40.0, 40.0)
    assert read_position(steps["c"]) is None


def test_resizing_a_member_writes_its_size_and_no_seat():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    resize_command(project, steps["b"].id, (0.0, 0.0), (300.0, 100.0)).redo(library)
    assert read_position(steps["b"]) is None
    assert read_size(steps["b"]) == (300.0, 100.0) and read_stack(steps["b"]) == "s1"
    resize_command(project, steps["a"].id, (392.0, 72.0), (300.0, 100.0)).redo(library)
    assert read_position(steps["a"]) == (392.0, 72.0) and read_stack(steps["a"]) == "s1"


def test_applying_a_layout_moves_the_first_member_and_the_rest_follow():
    library, project, steps = stacked()
    stack(library, steps, "a", "b", "c", seat=(400.0, 80.0))
    save_layout_command(project, "Plan", snapshot(library, project)).redo(library)
    [move] = position_commands(project, {steps["a"].id: (0.0, 600.0)}, "Move Step")
    move.redo(library)
    for command in apply_layout_commands(library, project, "Plan"):
        command.redo(library)
    placed = positions(library, project)
    assert placed[steps["a"].id] == (400.0, 80.0)
    assert_column(placed, steps, "a", "b", "c")
    assert all(read_position(steps[t]) is None for t in ("b", "c"))


def test_a_step_born_where_nobody_pointed_lands_clear_of_a_frame():
    library, project, steps = plan("a", "b")
    link(library, steps, "b", "a")
    stack(library, steps, "a", "b", seat=(40.0, 40.0))
    [box] = boxes(library, project)
    assert box == frame(read_stacks(project.steps)[0], (40.0, 40.0), lambda _m: (NODE_W, NODE_H))
    x, _y = free_spot(library, project)
    assert x > box[0] + box[2]


def test_an_entry_at_format_2_migrates_unchanged():
    entry = {"x": 40.0, "y": 80.0, "format": 2}
    assert migrated(entry, DATA_FORMAT) == {**entry, "format": DATA_FORMAT.version}
    assert write_member("s1")["format"] == DATA_FORMAT.version
