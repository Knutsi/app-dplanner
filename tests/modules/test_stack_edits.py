"""Editing a stack, and what may link to one — ``stack_edits.py`` and ``stacks.link_rule``,
with no Qt.

Two promises. **One in, one out**: with the rule installed, nothing a person links can land
in a stack's middle, and every builder leaves each stack one line. **Every edit is safe to
take back**: each builder is walked one part at a time, forward and back, and every graph on
the way is a part of the one before or the one after, with no cycle — ``stack_helpers.walk``
is that proof, run.
"""

import pytest
from tests.modules.stack_helpers import (
    assert_one_line,
    edges,
    link,
    plan,
    stack,
    stacked,
    state,
    walk,
)

from dplanner.domain.commands import (
    SetEdgesCommand,
    redirect_edges_command,
    remove_steps_command,
)
from dplanner.domain.model import SOURCE, WAITER, Step
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import (
    GRID,
    MODULE_ID,
    NODE_W,
    read_position,
    read_stack,
    write_position,
)
from dplanner.modules.project_editor.sorts import H_GAP
from dplanner.modules.project_editor.stack_edits import (
    add_command,
    bridged_removal,
    dissolve_command,
    insert_before_command,
    make_command,
    make_refusal,
    move_command,
    new_stack_command,
    take_out_command,
)
from dplanner.modules.project_editor.stacks import link_rule, read_stacks, stack_of, stray_links

SEAT = (400.0, 200.0)


def requires(steps, title):
    return steps[title].edges.get("requires", [])


def ids(steps, *titles):
    return [steps[title].id for title in titles]


def members(project, steps):
    """The titles of each stack's members, in chain order."""
    title = {step.id: name for name, step in steps.items()}
    return [[title.get(m, m) for m in found.members] for found in read_stacks(project.steps)]


def the_stack(project, steps, title="a"):
    found = stack_of(project.steps, steps[title].id)
    assert found is not None
    return found


# -- one in, one out ---------------------------------------------------------------------------


def test_a_link_into_a_stacks_middle_is_refused_and_names_its_first_step():
    library, _project, steps = stacked()
    refusal = library.link_refusal(steps["b"].id, "requires", steps["beside"].id)
    assert refusal == (
        "'b' is inside a stack: a link into it arrives at its first step, 'a' — "
        "or take 'b' out of the stack first"
    )
    with pytest.raises(ValueError, match="arrives at its first step"):
        library.set_edges(steps["b"].id, "requires", ids(steps, "a", "beside"))


def test_a_link_out_of_a_stacks_middle_is_refused_and_names_its_last_step():
    library, _project, steps = stacked()
    refusal = library.link_refusal(steps["beside"].id, "requires", steps["b"].id)
    assert refusal is not None and "leaves from its last step, 'c'" in refusal


def test_the_first_step_takes_links_in_and_the_last_sends_them_out():
    library, project, steps = stacked()
    link(library, steps, "a", "start", "beside")
    link(library, steps, "after", "c", "beside")
    assert_one_line(library, project)


def test_a_relates_link_is_never_the_stacks_business():
    library, project, steps = stacked()
    library.set_edges(steps["b"].id, "relates", [steps["beside"].id])
    library.set_edges(steps["beside"].id, "relates", [steps["b"].id])
    assert not stray_links(the_stack(project, steps), project.steps)


def test_a_gap_is_mended_by_the_link_it_lacks():
    library, project, steps = stacked()
    link(library, steps, "b")
    assert the_stack(project, steps).gaps
    link(library, steps, "b", "a")
    assert_one_line(library, project)


def test_the_graphs_own_refusals_come_before_the_rule():
    library, _project, steps = stacked()
    refusal = library.link_refusal(steps["a"].id, "requires", steps["c"].id)
    assert refusal is not None and "cycle" in refusal


def test_redirecting_a_chain_link_by_either_end_is_refused():
    """What makes one gesture safe: the redirect is judged against the graph as it stands,
    in which the chain link it would move still counts."""
    library, _project, steps = stacked()
    chain_link = (steps["b"].id, "requires", steps["a"].id)
    for end in (WAITER, SOURCE):
        plan_ = library.redirection([chain_link], steps["beside"].id, end)
        assert plan_.moving == () and len(plan_.refused) == 1
    redirect_edges_command(library, plan_, "Redirect Link").redo(library)
    assert requires(steps, "b") == [steps["a"].id]


def test_undoing_a_delete_restores_a_link_somebody_brought_into_a_stacks_middle():
    """A rule judges what a person links, never an undo: the link arrived from outside, and
    putting it back must not strand the composite halfway."""
    library, _project, steps = stacked()
    library.link_rules = ()
    link(library, steps, "b", "a", "beside")
    library.link_rules = (link_rule,)
    command = remove_steps_command(library, [steps["beside"].id], "Delete")
    command.redo(library)
    command.undo(library)
    assert requires(steps, "b") == ids(steps, "a", "beside")


# -- new and make ------------------------------------------------------------------------------


def test_a_new_stack_is_one_step_standing_where_it_was_put():
    library, project, _steps = plan("start")
    step = Step(title="Parse")
    walk(library, project, new_stack_command(project.id, step, seat=SEAT))
    assert read_position(step) == SEAT and read_stack(step)
    assert [found.members for found in read_stacks(project.steps)] == [(step.id,)]


def test_make_stacks_a_line_where_it_stands_and_changes_no_link():
    library, project, steps = plan("start", "a", "b", "c", "after")
    for waiter, source in (("a", "start"), ("b", "a"), ("c", "b"), ("after", "c")):
        link(library, steps, waiter, source)
    for title, seat in (("a", SEAT), ("b", (700.0, 200.0))):
        library.set_module_data(steps[title].id, MODULE_ID, write_position(*seat))
    before = edges(project)
    walk(library, project, make_command(library, ids(steps, "c", "a", "b")))
    assert members(project, steps) == [["a", "b", "c"]]
    assert edges(project) == before
    assert read_position(steps["a"]) == SEAT
    assert read_position(steps["b"]) is None  # The column derives it.
    assert_one_line(library, project)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda library, steps: link(library, steps, "c"), "'c' does not wait on 'b'"),
        (lambda library, steps: link(library, steps, "b", "a", "beside"), "'b' waits on 'beside'"),
        (lambda library, steps: link(library, steps, "beside", "b"), "'beside' waits on 'b'"),
        (lambda library, steps: stack(library, steps, "c", stack_id="s2"), "already in a stack"),
    ],
)
def test_make_refuses_what_is_not_one_free_line(change, said):
    library, _project, steps = plan("start", "a", "b", "c", "beside")
    for waiter, source in (("a", "start"), ("b", "a"), ("c", "b")):
        link(library, steps, waiter, source)
    library.link_rules = ()
    change(library, steps)
    refusal = make_refusal(library, ids(steps, "a", "b", "c"))
    assert refusal is not None and said in refusal
    with pytest.raises(ValueError, match=r"stack|line"):
        make_command(library, ids(steps, "a", "b", "c"))


# -- add ---------------------------------------------------------------------------------------


def test_a_step_added_at_the_end_takes_over_the_old_last_steps_dependents():
    library, project, steps = stacked()
    step = Step(title="d")
    walk(library, project, add_command(library, step, the_stack(project, steps)))
    assert [library.step(m).title for m in the_stack(project, steps).members] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert requires(steps, "after") == [step.id]
    assert step.edges["requires"] == [steps["c"].id]
    assert_one_line(library, project)


def test_a_step_added_in_front_takes_the_stacks_inputs_and_its_seat():
    library, project, steps = stacked(seat=SEAT)
    step = Step(title="zero")
    walk(library, project, add_command(library, step, the_stack(project, steps), 0))
    assert step.edges["requires"] == [steps["start"].id]
    assert requires(steps, "a") == [step.id]
    assert read_position(step) == SEAT and read_position(steps["a"]) is None
    assert_one_line(library, project)


def test_a_step_added_in_the_middle_is_spliced_into_the_chain():
    library, project, steps = stacked()
    step = Step(title="half")
    walk(library, project, add_command(library, step, the_stack(project, steps), 2))
    assert requires(steps, "c") == [step.id] and step.edges["requires"] == [steps["b"].id]
    assert_one_line(library, project)


def test_an_existing_step_arrives_with_no_links_of_its_own():
    library, project, steps = stacked()
    library.set_edges(steps["after"].id, "relates", [steps["beside"].id])
    walk(library, project, add_command(library, steps["beside"], the_stack(project, steps), 1))
    assert members(project, steps) == [["a", "beside", "b", "c"]]
    assert requires(steps, "beside") == [steps["a"].id]
    assert "relates" not in steps["after"].edges
    assert_one_line(library, project)


@pytest.mark.parametrize(("slot", "linked"), [(0, "a"), (None, "after")])
def test_a_step_already_linked_to_an_end_joins_without_waiting_on_itself(slot, linked):
    """In front, a step the first waited on; at the end, one that waited on the last."""
    library, project, steps = plan("start", "a", "b", "x")
    link(library, steps, "a", "start", "x") if linked == "a" else link(library, steps, "x", "b")
    link(library, steps, "b", "a")
    stack(library, steps, "a", "b")
    walk(library, project, add_command(library, steps["x"], the_stack(project, steps), slot))
    order = [["x", "a", "b"]] if slot == 0 else [["a", "b", "x"]]
    assert members(project, steps) == order
    assert_one_line(library, project)


def test_a_step_in_another_stack_is_refused_until_it_is_taken_out():
    library, project, steps = stacked()
    stack(library, steps, "beside", stack_id="s2")
    with pytest.raises(ValueError, match="take it out first"):
        add_command(library, steps["beside"], the_stack(project, steps))


# -- move and take out -------------------------------------------------------------------------


def test_moving_the_last_step_to_the_front_rewires_the_chain_and_hands_the_seat_on():
    library, project, steps = stacked(seat=SEAT)
    walk(library, project, move_command(library, the_stack(project, steps), steps["c"].id, 0))
    assert members(project, steps) == [["c", "a", "b"]]
    assert requires(steps, "c") == [steps["start"].id]
    assert requires(steps, "after") == [steps["b"].id]
    assert read_position(steps["c"]) == SEAT and read_position(steps["a"]) is None
    assert_one_line(library, project)


@pytest.mark.parametrize("taken", ["a", "b", "c"])
def test_a_step_taken_out_leaves_with_no_links_and_the_chain_closes(taken):
    library, project, steps = stacked(seat=SEAT)
    library.set_edges(steps[taken].id, "relates", [steps["beside"].id])
    walk(library, project, take_out_command(library, the_stack(project, steps), steps[taken].id))
    assert members(project, steps) == [[t for t in ("a", "b", "c") if t != taken]]
    assert library.boundary_edges([steps[taken].id]) == []
    assert not read_stack(steps[taken])
    assert read_position(steps["b" if taken == "a" else "a"]) == SEAT
    assert_one_line(library, project)


def test_the_last_step_taken_out_ends_the_stack():
    library, project, steps = plan("a")
    stack(library, steps, "a")
    take_out_command(library, the_stack(project, steps), steps["a"].id).redo(library)
    assert read_stacks(project.steps) == []


@pytest.mark.parametrize("build", ["add", "move", "take out"])
def test_a_stack_somebody_broke_is_mended_or_dissolved_before_it_is_edited(build):
    library, project, steps = stacked()
    library.link_rules = ()
    link(library, steps, "b", "a", "beside")
    found = the_stack(project, steps)
    with pytest.raises(ValueError, match=r"not one line: 'b' waits on 'beside'.*dissolve"):
        {
            "add": lambda: add_command(library, Step(title="d"), found),
            "move": lambda: move_command(library, found, steps["c"].id, 0),
            "take out": lambda: take_out_command(library, found, steps["b"].id),
        }[build]()


# -- dissolve ----------------------------------------------------------------------------------


def test_dissolving_lays_the_steps_in_a_row_and_pushes_what_lies_beyond():
    library, project, steps = stacked(seat=SEAT)
    far = (SEAT[0] + NODE_W + H_GAP, SEAT[1])
    library.set_module_data(steps["after"].id, MODULE_ID, write_position(*far))
    for title, seat in (("start", (0.0, 200.0)), ("beside", (0.0, 400.0))):
        library.set_module_data(steps[title].id, MODULE_ID, write_position(*seat))
    before = edges(project)
    walk(library, project, dissolve_command(library, the_stack(project, steps)))
    placed = positions(library, project)
    pitch = ((NODE_W + H_GAP) // GRID + ((NODE_W + H_GAP) % GRID > 0)) * GRID
    assert [placed[steps[t].id] for t in ("a", "b", "c")] == [
        (SEAT[0] + index * pitch, SEAT[1]) for index in range(3)
    ]
    assert placed[steps["after"].id] == (far[0] + 2 * pitch, far[1])
    assert placed[steps["start"].id] == (0.0, 200.0)
    assert read_stacks(project.steps) == [] and edges(project) == before


def test_a_stack_nobody_placed_dissolves_into_the_ambient_layout():
    library, project, steps = stacked()
    walk(library, project, dissolve_command(library, the_stack(project, steps)))
    assert read_stacks(project.steps) == []
    assert all(MODULE_ID not in step.module_data for step in project.steps)


def test_a_broken_stack_dissolves_and_the_undo_brings_it_back_broken():
    library, project, steps = stacked(seat=SEAT)
    library.link_rules = ()
    link(library, steps, "b", "a", "beside")
    link(library, steps, "c")
    before = state(project)
    command = dissolve_command(library, the_stack(project, steps))
    walk(library, project, command)
    command.undo(library)
    assert state(project) == before


# -- the removal Delete runs -------------------------------------------------------------------


@pytest.mark.parametrize("doomed", [("b",), ("a",), ("c",), ("a", "c"), ("a", "b", "c")])
def test_deleting_members_closes_the_chain_round_them(doomed):
    library, project, steps = stacked(seat=SEAT)
    walk(library, project, bridged_removal(library, ids(steps, *doomed), "Delete"))
    left = [t for t in ("a", "b", "c") if t not in doomed]
    assert members(project, steps) == ([left] if left else [])
    if left:
        assert requires(steps, left[0]) == [steps["start"].id]
        assert requires(steps, "after") == [steps[left[-1]].id]
        assert read_position(steps[left[0]]) == SEAT
    assert_one_line(library, project)


def test_deleting_the_middle_of_a_broken_stack_removes_it_plainly_and_is_undone():
    library, project, steps = stacked()
    library.link_rules = ()
    link(library, steps, "c", "b", "beside")
    library.link_rules = (link_rule,)
    walk(library, project, bridged_removal(library, ids(steps, "b"), "Delete"))
    assert requires(steps, "c") == [steps["beside"].id]


def test_a_link_picked_into_the_doomed_last_step_is_removed_not_moved():
    library, project, steps = stacked()
    picked = [(steps["after"].id, "requires", steps["c"].id)]
    walk(library, project, bridged_removal(library, ids(steps, "c"), "Delete", links=picked))
    assert requires(steps, "after") == []
    assert requires(steps, "b") == [steps["a"].id]


def test_two_stacks_losing_their_last_steps_both_reach_one_dependent():
    library, project, steps = plan("a", "b", "x", "y", "after")
    link(library, steps, "b", "a")
    link(library, steps, "y", "x")
    link(library, steps, "after", "b", "y")
    stack(library, steps, "a", "b")
    stack(library, steps, "x", "y", stack_id="s2")
    walk(library, project, bridged_removal(library, ids(steps, "b", "y"), "Delete"))
    assert sorted(requires(steps, "after")) == sorted(ids(steps, "a", "x"))


def test_a_neighbouring_stack_somebody_broke_does_not_refuse_a_delete():
    """The link that moves ends in a stack broken from outside; the rewire carries it rather
    than judging it again, so the Delete neither refuses nor strands itself."""
    library, project, steps = stacked()
    extra = Step(title="t1")
    library.add_child(project.id, extra)
    steps["t1"] = extra
    steps["y"] = Step(title="y")
    library.add_child(project.id, steps["y"])
    library.link_rules = ()
    link(library, steps, "y", "t1", "c")
    stack(library, steps, "t1", "y", stack_id="s2")
    library.link_rules = (link_rule,)
    walk(library, project, bridged_removal(library, ids(steps, "c"), "Delete"))
    assert requires(steps, "y") == ids(steps, "t1", "b")


def test_a_link_that_no_longer_resolves_stays_where_it_is():
    library, project, steps = stacked()
    ghost = "0" * 32
    steps["a"].edges["requires"].append(ghost)
    walk(library, project, take_out_command(library, the_stack(project, steps), steps["a"].id))
    assert requires(steps, "a") == [ghost]
    assert requires(steps, "b") == [steps["start"].id]


def test_a_kind_this_build_does_not_know_is_carried():
    library, project, steps = stacked()
    steps["b"].edges["blocks"] = [steps["beside"].id]
    walk(library, project, take_out_command(library, the_stack(project, steps), steps["b"].id))
    assert steps["b"].edges == {"blocks": [steps["beside"].id]}


# -- insert before ----------------------------------------------------------------------------


def test_inserting_before_a_loose_step_takes_over_what_it_waited_on():
    library, project, steps = plan("start", "other", "step")
    link(library, steps, "step", "start", "other")
    wait = Step(title="Wait")
    walk(
        library,
        project,
        insert_before_command(library, wait, steps["step"].id, "Insert Wait", seat=SEAT),
    )
    assert wait.edges["requires"] == ids(steps, "start", "other")
    assert requires(steps, "step") == [wait.id]
    assert read_position(wait) == SEAT and not read_stack(wait)


@pytest.mark.parametrize(("before", "slot"), [("a", 0), ("b", 1), ("c", 2)])
def test_inserting_before_a_member_joins_its_stack_in_that_slot(before, slot):
    library, project, steps = stacked(seat=SEAT)
    wait = Step(title="Wait")
    walk(library, project, insert_before_command(library, wait, steps[before].id, "Insert Wait"))
    assert the_stack(project, steps).members.index(wait.id) == slot
    assert read_position(steps["a"] if slot else wait) == SEAT
    assert_one_line(library, project)


def test_inserting_before_a_member_of_a_broken_stack_is_never_refused():
    library, project, steps = stacked()
    library.link_rules = ()
    link(library, steps, "b", "a", "beside")
    wait = Step(title="Wait")
    walk(library, project, insert_before_command(library, wait, steps["b"].id, "Insert Wait"))
    assert wait.edges["requires"] == ids(steps, "a", "beside")


def test_a_set_edges_command_asks_the_rule_on_its_first_redo_only():
    """A redo replayed after the undo is not a gesture: another writer may have changed the
    stack since, and the replay must land rather than strand the history."""
    library, project, steps = stacked()
    command = SetEdgesCommand(steps["beside"].id, "requires", ids(steps, "start", "c"))
    command.redo(library)
    command.undo(library)
    # Another writer puts a step after the last, so 'c' is in the middle now.
    library.link_rules = ()
    steps["d"] = Step(title="d")
    library.add_child(project.id, steps["d"])
    link(library, steps, "d", "c")
    stack(library, steps, "a", "b", "c", "d")
    library.link_rules = (link_rule,)
    assert library.link_refusal(steps["beside"].id, "requires", steps["c"].id) is not None
    command.redo(library)
    assert requires(steps, "beside") == ids(steps, "start", "c")
