"""Wave view's arrangement: every card in the column of its dependency depth.

No Qt — ``sorts.arranged_in_waves`` is a pure function over the model. What is pinned here is
what Wave view must keep doing while it is shown live: land the same way every time, and
hold still — a link moves only the steps whose wave it changes, and nobody else swaps places.
"""

import random
from itertools import pairwise

from tests.modules.stack_helpers import stacked
from tests.modules.test_graph_layout import assert_no_overlap, braided, steps_by_id

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import depths
from dplanner.domain.schedule import earliest_starts
from dplanner.modules.project_editor.positions import GRID, NODE_H, NODE_W, node_size
from dplanner.modules.project_editor.positions import write_position as seat_entry
from dplanner.modules.project_editor.sorts import (
    H_GAP,
    ORIGIN,
    V_GAP,
    arranged_in_waves,
    waves,
)
from dplanner.modules.project_editor.stacks import FRAME_PAD


def default_size(_step):
    return (NODE_W, NODE_H)


def column_of(arrangement):
    return {step_id: wave.depth for wave in arrangement.waves for step_id in wave.steps}


def random_plan(seed, size=14):
    """A seeded graph whose links only ever run from an earlier step to a later one — so any
    link added the same way can never close a cycle — with an estimate on most steps."""
    rng = random.Random(seed)
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    steps = [Step(title=f"s{index}") for index in range(size)]
    for step in steps:
        library.add_child(project.id, step)
    for later in range(1, size):
        sources = [steps[i].id for i in range(later) if rng.random() < 0.18]
        if sources:
            SetEdgesCommand(steps[later].id, "requires", sources).redo(library)
    days = {step.id: rng.choice([None, 0.5, 1.0, 1.5, 2.0]) for step in steps}
    return library, project, steps, (lambda step: days[step.id]), rng


def downstream(project, step_id):
    """``step_id`` and everything that waits on it, directly or through others."""
    found = {step_id}
    changed = True
    while changed:
        changed = False
        for step in project.steps:
            if step.id not in found and found & set(step.edges.get("requires", [])):
                found.add(step.id)
                changed = True
    return found


def order_among(arrangement, keep):
    """Each column's cards from ``keep``, top to bottom — the columns holding any."""
    found = {wave.depth: [s for s in wave.steps if s in keep] for wave in arrangement.waves}
    return {depth: cards for depth, cards in found.items() if cards}


def test_waves_land_the_same_way_every_time_whatever_the_edge_order():
    library, project, _steps = braided()
    first = waves(library, project)
    assert waves(library, project) == first
    flipped_library, flipped_project, _ = braided(flip_edges=True)
    assert list(waves(flipped_library, flipped_project).values()) == list(first.values())


def test_a_card_stands_in_the_column_of_its_depth_and_the_columns_start_together_at_the_top():
    library, project, steps = braided()
    arrangement = arranged_in_waves(library, project, default_size)
    by_depth = depths(library, project)
    seats = arrangement.seats
    xs = {wave.depth: wave.left for wave in arrangement.waves}
    for step in project.steps:
        assert seats[step.id][0] == xs[by_depth[step.id]]
    for wave in arrangement.waves:
        assert seats[wave.steps[0]][1] == ORIGIN  # Top-aligned, never centred.
    pitches = {right - left for left, right in pairwise(xs.values())}
    assert len(pitches) == 1  # One pitch under the default size, whatever each column holds.
    assert all(x % GRID == 0 and y % GRID == 0 for x, y in seats.values())
    rows = [seats[s][1] for s in arrangement.waves[1].steps]
    assert all(b - a == NODE_H + V_GAP for a, b in pairwise(rows))
    assert pitches.pop() >= NODE_W + H_GAP
    assert steps["loose"].id in arrangement.waves[0].steps


def test_adding_one_link_changes_the_wave_of_only_the_waiter_and_what_follows_it():
    for seed in range(60):
        library, project, steps, days_for, rng = random_plan(seed)
        before = arranged_in_waves(library, project, default_size, days_for)
        later = rng.randrange(1, len(steps))
        waiter = steps[later]
        source = steps[rng.randrange(0, later)]
        sources = waiter.edges.get("requires", [])
        if source.id in sources:
            continue
        SetEdgesCommand(waiter.id, "requires", [*sources, source.id]).redo(library)
        after = arranged_in_waves(library, project, default_size, days_for)

        movers = downstream(project, waiter.id)
        was, now = column_of(before), column_of(after)
        assert {s for s in was if was[s] != now[s]} <= movers, seed
        # Everybody else keeps their place among the others who stayed.
        rest = set(was) - movers
        assert order_among(before, rest) == order_among(after, rest), seed
        # A column nobody moved into or out of does not move at all.
        for wave in before.waves:
            touched = any(s in movers for s in wave.steps) or any(
                now[s] == wave.depth for s in movers
            )
            if not touched:
                assert all(before.seats[s] == after.seats[s] for s in wave.steps), seed


def test_removing_one_link_changes_the_wave_of_only_the_cards_whose_depth_changed():
    for seed in range(60):
        library, project, steps, days_for, rng = random_plan(seed)
        linked = [step for step in steps if step.edges.get("requires")]
        if not linked:
            continue
        waiter = rng.choice(linked)
        sources = waiter.edges["requires"]
        dropped = rng.choice(sources)
        depth_before = depths(library, project)
        before = arranged_in_waves(library, project, default_size, days_for)
        SetEdgesCommand(waiter.id, "requires", [s for s in sources if s != dropped]).redo(library)
        depth_after = depths(library, project)
        after = arranged_in_waves(library, project, default_size, days_for)

        deeper_or_not = {s for s in depth_before if depth_before[s] != depth_after[s]}
        was, now = column_of(before), column_of(after)
        assert {s for s in was if was[s] != now[s]} == deeper_or_not, seed
        rest = set(was) - downstream(project, waiter.id)
        assert order_among(before, rest) == order_among(after, rest), seed


def test_down_a_column_steps_go_by_earliest_start_then_highest_source_then_project_order():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    titles = ("long", "short", "x", "late", "early", "tie")
    steps = {title: Step(title=title) for title in titles}
    for step in steps.values():
        library.add_child(project.id, step)
    days = {"long": 3.0, "short": 1.0}

    def link(waiter, *sources):
        SetEdgesCommand(steps[waiter].id, "requires", [steps[s].id for s in sources]).redo(library)

    link("late", "long")  # Starts on day 3.
    link("early", "short")  # Starts on day 1: above "late", though later in project order.
    link("tie", "short")  # Day 1 too, behind the same source: project order breaks the tie.
    arrangement = arranged_in_waves(
        library, project, default_size, lambda step: days.get(step.title)
    )
    second = [library.step(s).title for s in arrangement.waves[1].steps]
    assert second == ["early", "tie", "late"]

    # With no estimates every start is day 0, and a card follows its highest source.
    unestimated = arranged_in_waves(library, project, default_size)
    first = [library.step(s).title for s in unestimated.waves[0].steps]
    second = [library.step(s).title for s in unestimated.waves[1].steps]
    assert first == ["long", "short", "x"]
    assert second == ["late", "early", "tie"]


def test_a_stack_stands_in_one_wave_as_one_card():
    library, project, steps = stacked()
    arrangement = arranged_in_waves(library, project, default_size)
    column = column_of(arrangement)
    ids = {title: step.id for title, step in steps.items()}
    assert column[ids["start"]] == 0
    assert column[ids["a"]] == column[ids["b"]] == column[ids["c"]] == 1
    # What follows takes its depth from the stack as one node, not from its last card.
    assert column[ids["after"]] == 2
    seats = arrangement.seats
    wave = arrangement.waves[1]
    # The stack's cards stand in the column; its frame stands outside them.
    assert seats[ids["a"]][0] == seats[ids["b"]][0] == seats[ids["c"]][0] == wave.left
    assert seats[ids["a"]][1] == ORIGIN + FRAME_PAD
    assert seats[ids["a"]][1] < seats[ids["b"]][1] < seats[ids["c"]][1]
    assert wave.right - wave.left == NODE_W


def test_a_stack_arriving_in_a_column_moves_no_other_column():
    loose_library, loose_project, loose_steps = stacked()
    # The same plan with its stack dissolved: the members become three waves of their own.
    for title in ("a", "b", "c"):
        loose_library.set_module_data(loose_steps[title].id, "project_editor", None)
    stacked_library, stacked_project, _ = stacked()
    with_stack = arranged_in_waves(stacked_library, stacked_project, default_size)
    without = arranged_in_waves(loose_library, loose_project, default_size)
    assert [w.left for w in with_stack.waves] == [w.left for w in without.waves][:3]


def test_keep_spaces_the_same_arrangement_for_each_cards_own_size():
    library, project, steps = braided()
    wide = steps["d"]
    library.set_module_data(wide.id, "project_editor", seat_entry(0, 0, (400.0, 200.0)))
    shown = arranged_in_waves(library, project, default_size)
    kept = arranged_in_waves(library, project, node_size)
    assert column_of(shown) == column_of(kept)
    assert [w.steps for w in shown.waves] == [w.steps for w in kept.waves]
    assert_no_overlap(kept.seats, node_size, steps_by_id(project))


def test_each_wave_runs_from_its_earliest_start_to_its_latest_finish():
    library, project, _steps, days_for, _rng = random_plan(7)
    starts = earliest_starts(library, project, days_for)
    arrangement = arranged_in_waves(library, project, default_size, days_for)
    for wave in arrangement.waves:
        assert wave.start == min(starts[s] for s in wave.steps)
        assert wave.finish == max(
            starts[s] + (days_for(library.step(s)) or 0.0) for s in wave.steps
        )


def test_a_stack_lasts_as_long_as_its_members_together_on_the_ruler():
    library, project, steps = stacked()
    days = {"start": 1.0, "a": 1.0, "b": 2.0, "c": 0.5}
    arrangement = arranged_in_waves(
        library, project, default_size, lambda step: days.get(step.title)
    )
    stack_wave = arrangement.waves[1]
    assert (stack_wave.start, stack_wave.finish) == (1.0, 4.5)
    assert (arrangement.waves[2].start, arrangement.waves[2].finish) == (4.5, 4.5)
    assert steps["after"].id in arrangement.waves[2].steps


def test_an_empty_project_has_no_waves():
    library = Library()
    project = Project(title="Empty")
    library.add_child(library.id, project)
    assert arranged_in_waves(library, project).waves == ()
    assert waves(library, project) == {}
