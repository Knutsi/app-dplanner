"""Where a node goes when nobody has placed it.

No ``qapp`` fixture: the placement rules are plain functions over the model, which is the
whole reason they live in their own file. The dependency walk they build on is the domain's
and is tested in ``tests/domain/test_ordering.py``; what is tested here is where a node
ends up on screen.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import depths
from dplanner.modules.project_editor.geometry import (
    as_json,
    map_text,
    measure,
    pitches,
    shift,
)
from dplanner.modules.project_editor.geometry import text as geometry_text
from dplanner.modules.project_editor.placement import auto_positions, positions
from dplanner.modules.project_editor.positions import (
    GRID,
    NODE_H,
    NODE_W,
    node_size,
    read_position,
    snapped,
    write_position,
)
from dplanner.modules.project_editor.sorts import (
    DAY_PX,
    H_GAP,
    H_PITCH,
    ORIGIN,
    V_GAP,
    V_PITCH,
    hole,
    lanes,
    layered_down,
    layered_flow,
    measured,
    most_connected,
    radial,
    spine,
    tidy,
    timeline,
)


def build():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "B", "C"):
        library.add_child(project.id, Step(title=title))
    return library, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def test_a_chain_reads_left_to_right():
    library, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [b.id]).redo(library)

    found = depths(library, project)
    assert (found[a.id], found[b.id], found[c.id]) == (0, 1, 2)
    placed = auto_positions(library, project)
    assert placed[a.id][0] < placed[b.id][0] < placed[c.id][0]


def test_independent_steps_stack_in_one_column():
    library, project = build()
    placed = auto_positions(library, project)
    xs = {placed[step.id][0] for step in project.steps}
    ys = {placed[step.id][1] for step in project.steps}
    assert len(xs) == 1 and len(ys) == 3


def test_the_longest_chain_wins():
    """A step waiting on two things sits after the later of them, not the earlier."""
    library, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [a.id, b.id]).redo(library)
    assert depths(library, project)[c.id] == 2


def test_a_stored_position_wins_over_the_automatic_one():
    library, project = build()
    step = by_title(project, "B")
    library.set_module_data(step.id, "project_editor", write_position(504.0, 304.0))
    placed = positions(library, project)
    assert placed[step.id] == (504.0, 304.0)  # Already on the grid, so stored verbatim.
    assert (
        placed[by_title(project, "A").id]
        == auto_positions(library, project)[by_title(project, "A").id]
    )


def test_a_fully_placed_project_never_computes_the_automatic_layout(monkeypatch):
    """Every canvas sync asks for positions; a settled plan must not pay a layout for it."""
    library, project = build()
    for index, step in enumerate(project.steps):
        library.set_module_data(step.id, "project_editor", write_position(8.0 * index, 0.0))

    def refuse(*_args):
        raise AssertionError("the automatic layout was computed for a fully placed project")

    monkeypatch.setattr("dplanner.modules.project_editor.placement.auto_positions", refuse)
    placed = positions(library, project)
    assert placed[project.steps[2].id] == (16.0, 0.0)


def test_positions_are_stored_as_whole_unit_floats():
    """FORMAT.md's numeric rule: an int would write as 8 where a reloaded float writes 8.0.
    Snapping to the grid is the gesture's business, never the write's — a CLI verb stores
    what it was given, to the unit."""
    entry = write_position(11.4, 3.6)
    assert entry["x"] == 11.0 and entry["y"] == 4.0
    assert isinstance(entry["x"], float)
    assert GRID == 8.0 and snapped(11.0, GRID) == 8.0


def test_a_size_is_stored_beside_the_position_and_absence_is_the_default():
    """Only a card somebody resized carries ``w`` and ``h``; a card at the default footprint
    stores none, so a project of untouched cards never learns the keys exist."""
    from dplanner.modules.project_editor.positions import MIN_NODE_H, MIN_NODE_W, read_size

    library, project = build()
    step = project.steps[0]
    assert read_size(step) is None
    assert node_size(step) == (NODE_W, NODE_H)

    entry = write_position(8.0, 16.0, (300.4, 160.0))
    assert (entry["w"], entry["h"]) == (300.0, 160.0)
    assert isinstance(entry["w"], float)
    library.set_module_data(step.id, "project_editor", entry)
    assert read_size(step) == (300.0, 160.0) and node_size(step) == (300.0, 160.0)

    assert "w" not in write_position(8.0, 16.0, (NODE_W, NODE_H))
    assert "w" not in write_position(8.0, 16.0, None)
    small = write_position(0.0, 0.0, (10.0, 10.0))
    assert (small["w"], small["h"]) == (MIN_NODE_W, MIN_NODE_H)
    library.set_module_data(step.id, "project_editor", {"x": 1.0, "y": 2.0, "w": "wide", "h": 5})
    assert read_size(step) is None and read_position(step) == (1.0, 2.0)


def test_the_sorts_space_by_the_size_a_card_was_given():
    """``size_for`` defaults to the stored footprint, so a card dragged larger keeps its
    room in every arrangement without any algorithm learning about sizes."""
    library, project, steps = braided()
    library.set_module_data(
        steps["c"].id, "project_editor", write_position(0.0, 0.0, (400.0, 300.0))
    )
    by_id = {step.id: step for step in project.steps}
    # Radial's rings are a fixed pitch and it is not size-aware today, as the battery above
    # already says; the four that space by size keep a large card clear of its neighbours.
    for sort in (layered_flow, layered_down, spine, timeline):
        placed = sort(library, project)
        assert_no_overlap(placed, size_for=node_size, steps_by_id=by_id)


def test_one_row_below_a_tall_card_clears_it():
    from dplanner.modules.project_editor.placement import below
    from dplanner.modules.project_editor.sorts import V_GAP

    assert below(40.0, 40.0) == (40.0, 40.0 + NODE_H + V_GAP)
    assert below(40.0, 40.0, 300.0) == (40.0, 40.0 + 300.0 + V_GAP)


def test_an_unreadable_position_reads_as_absent():
    """A hand-edited or newer file must not crash the canvas."""
    library, project = build()
    step = project.steps[0]
    library.set_module_data(step.id, "project_editor", {"x": "left", "y": 4})
    assert read_position(step) is None


# -- the sort battery ---------------------------------------------------------------------------
#
# Every sort must be deterministic (same graph, same result — ties break by project order),
# size-aware (spacing follows what size_for answers), and leave no two nodes overlapping.


def braided(flip_edges=False):
    """Two chains that cross, a shared gate, and a loose end — enough shape to tangle."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    steps = {}
    for title in ("a", "b", "c", "d", "e", "f", "g", "loose"):
        step = Step(title=title)
        steps[title] = step
        library.add_child(project.id, step)

    def link(waiter, sources):
        ordered = list(reversed(sources)) if flip_edges else sources
        SetEdgesCommand(steps[waiter].id, "requires", [steps[s].id for s in ordered]).redo(library)

    link("c", ["b"])
    link("d", ["a"])
    link("e", ["c", "d"])
    link("f", ["d", "c"])
    link("g", ["e", "f"])
    return library, project, steps


def assert_no_overlap(placed, size_for=node_size, steps_by_id=None):
    rects = []
    for step_id, (x, y) in placed.items():
        w, h = size_for(steps_by_id[step_id]) if steps_by_id else (180.0, 56.0)
        rects.append((step_id, x, y, w, h))
    for i, (one, x1, y1, w1, h1) in enumerate(rects):
        for other, x2, y2, w2, h2 in rects[i + 1 :]:
            apart = x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
            assert apart, f"{one} overlaps {other}"


def every_sort(library, project):
    return {
        "flow": layered_flow(library, project),
        "down": layered_down(library, project),
        "spine": spine(library, project),
        "timeline": timeline(library, project),
        "radial": radial(library, project),
    }


def test_every_sort_is_deterministic_and_overlap_free():
    library, project, _steps = braided()
    first = every_sort(library, project)
    again = every_sort(library, project)
    for name, placed in first.items():
        assert placed.keys() == {step.id for step in project.steps}
        assert placed == again[name], f"{name} is not deterministic"
        assert_no_overlap(placed)


def test_edge_list_order_does_not_change_a_sort():
    library, project, steps = braided()
    flipped_library, flipped_project, flipped_steps = braided(flip_edges=True)
    one = every_sort(library, project)
    other = every_sort(flipped_library, flipped_project)
    for name in one:
        by_title = {title: one[name][step.id] for title, step in steps.items()}
        flipped = {title: other[name][step.id] for title, step in flipped_steps.items()}
        assert by_title == flipped, f"{name} depends on edge insertion order"


def test_flow_keeps_left_to_right_depth_order():
    library, project, _steps = braided()
    placed = layered_flow(library, project)
    for step in project.steps:
        for source in step.edges.get("requires", []):
            assert placed[source][0] < placed[step.id][0]


def test_barycenter_untangles_a_crossing():
    library, project = build()
    a, b, c = project.steps
    d = Step(title="D")
    library.add_child(project.id, d)
    # C waits on B and D waits on A: laid in project order the two edges would cross.
    SetEdgesCommand(c.id, "requires", [b.id]).redo(library)
    SetEdgesCommand(d.id, "requires", [a.id]).redo(library)

    placed = layered_flow(library, project)
    same_side = (placed[a.id][1] < placed[b.id][1]) == (placed[d.id][1] < placed[c.id][1])
    assert same_side, "the second column should mirror the first's order"


def test_layered_down_flows_top_to_bottom():
    library, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [b.id]).redo(library)
    placed = layered_down(library, project)
    assert placed[a.id][1] < placed[b.id][1] < placed[c.id][1]


def test_spine_lays_the_longest_chain_on_one_line():
    library, project, steps = braided()
    placed = spine(library, project)
    # b → c → e → g is the deepest chain through the first-by-project-order sources.
    chain = [steps[t].id for t in ("b", "c", "e", "g")]
    assert {placed[sid][1] for sid in chain} == {0.0}
    xs = [placed[sid][0] for sid in chain]
    assert xs == sorted(xs)
    off_spine = [sid for sid in placed if sid not in chain]
    assert all(placed[sid][1] != 0.0 for sid in off_spine)


def test_spine_ribs_alternate_sides():
    library, project, _steps = braided()
    placed = spine(library, project)
    sides = {1.0 if y > 0 else -1.0 for _x, y in placed.values() if y != 0.0}
    assert sides == {1.0, -1.0}


def test_timeline_x_follows_earliest_start():
    library, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    days = {a.id: 2.0}
    placed = timeline(library, project, days_for=lambda step: days.get(step.id))

    assert placed[a.id][0] == ORIGIN
    assert placed[c.id][0] == ORIGIN  # nothing to wait on
    assert placed[b.id][0] == ORIGIN + 2.0 * DAY_PX
    assert_no_overlap(placed)


def test_radial_rings_follow_bfs_distance():
    library, project = build()
    a, b, c = project.steps
    d = Step(title="D")
    library.add_child(project.id, d)
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(d.id, "requires", [b.id]).redo(library)

    def r(placed, step):
        x, y = placed[step.id]
        cx, cy = x + NODE_W / 2, y + NODE_H / 2  # the node's centre, for the default size
        return (cx**2 + cy**2) ** 0.5

    placed = radial(library, project)  # a is the most connected, so the centre
    assert r(placed, a) < 1e-9
    assert abs(r(placed, b) - r(placed, c)) < 1e-9
    assert r(placed, d) > r(placed, b)

    recentred = radial(library, project, center=d.id)
    assert r(recentred, d) < 1e-9
    assert most_connected(library, project) == a.id


def test_sorts_respect_node_sizes():
    library, project, steps = braided()
    big = steps["c"].id

    def size_for(step):
        return (360.0, 200.0) if step.id == big else (180.0, 56.0)

    by_id = {step.id: step for step in project.steps}
    for sort in (layered_flow, layered_down, spine, timeline):
        placed = sort(library, project, size_for=size_for)
        assert_no_overlap(placed, size_for=size_for, steps_by_id=by_id)


# -- tidy ---------------------------------------------------------------------------------------
#
# The sixth sort starts from the picture rather than the graph. Its contract: no overlaps,
# the left-to-right and top-to-bottom order of what was there kept, every hole within the
# threshold, everything on the grid and at the origin — and idempotent, so a tidied graph
# tidies to itself and a sorted one to itself snapped.


def on_grid(placed):
    return all(x % GRID == 0 and y % GRID == 0 for x, y in placed.values())


def steps_by_id(project):
    return {step.id: step for step in project.steps}


def chain_of(*titles):
    """A project whose steps require each other in order — one card per column."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    previous = None
    for title in titles:
        step = Step(title=title)
        library.add_child(project.id, step)
        if previous is not None:
            SetEdgesCommand(step.id, "requires", [previous.id]).redo(library)
        previous = step
    return library, project


def test_tidy_resolves_overlaps_and_lands_on_the_grid():
    library, project, steps = braided()
    placed = layered_flow(library, project)
    placed[steps["b"].id] = placed[steps["a"].id]  # two cards dropped on one spot
    x, y = placed[steps["e"].id]
    placed[steps["e"].id] = (x + 3.0, y - 5.0)  # and one knocked off the grid

    tidied = tidy(project, placed)

    assert tidied.keys() == placed.keys()
    assert_no_overlap(tidied, size_for=node_size, steps_by_id=steps_by_id(project))
    assert on_grid(tidied)
    assert min(x for x, _y in tidied.values()) == ORIGIN
    assert min(y for _x, y in tidied.values()) == ORIGIN
    # The two that shared a spot keep their column and stack, the earlier one on top.
    a, b = tidied[steps["a"].id], tidied[steps["b"].id]
    assert a[0] == b[0] and a[1] < b[1]


def test_tidy_keeps_left_to_right_and_top_to_bottom_order():
    library, project, _steps = braided()
    for scattered in (spine(library, project), radial(library, project)):
        tidied = tidy(project, scattered)
        for one in scattered:
            for other in scattered:
                if scattered[other][0] - scattered[one][0] > H_PITCH / 2:
                    assert tidied[one][0] < tidied[other][0]
                if scattered[other][1] - scattered[one][1] > V_PITCH / 2:
                    assert tidied[one][1] < tidied[other][1]


def test_tidy_is_idempotent_and_deterministic():
    library, project, _steps = braided()
    for placed in (
        layered_flow(library, project),
        spine(library, project),
        radial(library, project),
    ):
        once = tidy(project, placed)
        assert tidy(project, placed) == once
        assert tidy(project, once) == once
        assert_no_overlap(once, size_for=node_size, steps_by_id=steps_by_id(project))


def test_tidy_is_idempotent_beside_a_tall_card():
    """Two cards overlapping in one column next to a card three rows tall: the lower one
    takes a sub-row of its own, and the second run finds the same rows — a stack inside
    the cell beside the tall card did not."""
    library, project = build()
    d = Step(title="D")
    library.add_child(project.id, d)
    a, b, c, _d = project.steps
    tall = {c.id: (NODE_W, 300.0)}

    def size_for(step):
        return tall.get(step.id, (NODE_W, NODE_H))

    placed = {a.id: (40.0, 40.0), b.id: (40.0, 50.0), c.id: (340.0, 40.0), d.id: (40.0, 400.0)}
    once = tidy(project, placed, size_for)
    assert tidy(project, once, size_for) == once
    assert_no_overlap(once, size_for=size_for, steps_by_id=steps_by_id(project))
    assert once[a.id][1] < once[b.id][1] < once[d.id][1]


def test_tidy_of_a_sorted_graph_is_the_sorted_graph_snapped():
    """The column pitch (300) is not a multiple of the grid (8), so a flow's alternate
    columns move by four points and nothing else changes."""
    library, project = chain_of("A", "B", "C")
    flow = layered_flow(library, project)
    assert tidy(project, flow) == {
        i: (snapped(x, GRID), snapped(y, GRID)) for i, (x, y) in flow.items()
    }
    assert [tidy(project, flow)[step.id][0] for step in project.steps] == [40.0, 336.0, 640.0]


def test_tidy_rounds_a_flows_half_pitch_centring_to_a_row():
    """Flow centres a column against the tallest, so a 1-3-2 graph puts the lone card and
    the pair half a row off the three. Tidy reads them into the nearest rows: three rows,
    the same height, the lone card where it was."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    a = Step(title="A")
    library.add_child(project.id, a)
    bs = [Step(title=f"B{i}") for i in range(3)]
    cs = [Step(title=f"C{i}") for i in range(2)]
    for step in (*bs, *cs):
        library.add_child(project.id, step)
    for b in bs:
        SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    for c in cs:
        SetEdgesCommand(c.id, "requires", [bs[0].id]).redo(library)
    flow = layered_flow(library, project)
    assert flow[a.id] == (ORIGIN, 160.0) and flow[cs[0].id][1] == 100.0

    tidied = tidy(project, flow)

    assert tidied[a.id] == (ORIGIN, 160.0)
    assert sorted(tidied[c.id][1] for c in cs) == [40.0, 160.0]
    assert {y for _x, y in tidied.values()} == {40.0, 160.0, 280.0}
    height = max(y for _x, y in tidied.values()) - min(y for _x, y in tidied.values())
    assert height == max(y for _x, y in flow.values()) - min(y for _x, y in flow.values())


def test_tidy_evens_jitter_to_the_pitch():
    library, project = chain_of("A", "B", "C")
    flow = layered_flow(library, project)
    jitter = [(3.0, -2.0), (-5.0, 6.0), (7.0, -7.0)]
    jittered = {
        step.id: (flow[step.id][0] + dx, flow[step.id][1] + dy)
        for step, (dx, dy) in zip(project.steps, jitter, strict=True)
    }
    assert tidy(project, jittered) == tidy(project, flow)


def test_tidy_closes_a_hole_wider_than_the_threshold_and_keeps_one_within_it():
    _library, project = build()
    a, b, c = project.steps
    far = {a.id: (40.0, 40.0), b.id: (40.0 + 4 * H_PITCH, 40.0), c.id: (40.0, 400.0)}
    assert tidy(project, far, air=1)[b.id][0] == 336.0  # three empty columns: closed
    assert tidy(project, far, air=2)[b.id][0] == 336.0  # wider than the threshold: closed
    assert tidy(project, far, air=5)[b.id][0] == 1240.0  # within it: kept
    near = {a.id: (40.0, 40.0), b.id: (40.0 + 2 * H_PITCH, 40.0), c.id: (40.0, 400.0)}
    assert tidy(project, near, air=2)[b.id][0] == 640.0  # one empty column: air, kept
    assert tidy(project, near, air=1)[b.id][0] == 336.0


def test_tidy_keeps_a_kept_empty_row_with_an_off_grid_height():
    """A card 70 tall with one empty row under it: the snapped seat is eight points short
    of a whole pitch, and a floor would have closed the row on the second run."""
    _library, project = build()
    a, b, _c = project.steps
    short = {a.id: (NODE_W, 70.0), _c.id: (NODE_W, 70.0)}  # both cards in the row are short

    def size_for(step):
        return short.get(step.id, (NODE_W, NODE_H))

    placed = {a.id: (40.0, 40.0), b.id: (40.0, 40.0 + 70.0 + V_GAP + V_PITCH), _c.id: (340.0, 40.0)}
    once = tidy(project, placed, size_for)
    assert once[b.id][1] == 272.0
    assert tidy(project, once, size_for) == once


def holes_after(project, tidied):
    """Every lane's hole count on each axis, re-measured from a tidied picture."""
    by_id = steps_by_id(project)
    ids = list(tidied)
    found = []
    for axis, gap, pitch in ((0, H_GAP, H_PITCH), (1, V_GAP, V_PITCH)):

        def low(step_id, axis=axis):
            return tidied[step_id][axis]

        def size(step_id, axis=axis):
            return node_size(by_id[step_id])[axis]

        found += [
            hole(lane, gap, pitch) for lane in measured(lanes(ids, low, pitch / 2), low, size)
        ]
    return found


def test_tidy_leaves_every_hole_within_the_threshold():
    library, project, steps = braided()
    scattered = spine(library, project)
    scattered[steps["loose"].id] = (5000.0, -3000.0)
    for air in (1, 2, 3):
        assert max(holes_after(project, tidy(project, scattered, air=air))) <= air - 1


def test_tidy_respects_custom_sizes():
    library, project, steps = braided()
    library.set_module_data(
        steps["c"].id, "project_editor", write_position(0.0, 0.0, (400.0, 300.0))
    )
    placed = layered_flow(library, project)
    once = tidy(project, placed)
    assert_no_overlap(once, size_for=node_size, steps_by_id=steps_by_id(project))
    assert tidy(project, once) == once


def test_tidy_of_nothing_is_nothing():
    library = Library()
    project = Project(title="Empty")
    library.add_child(library.id, project)
    assert tidy(project, {}) == {}
    only = Step(title="Only")
    library.add_child(project.id, only)
    assert tidy(project, {only.id: (900.0, -50.0)}) == {only.id: (ORIGIN, ORIGIN)}


# -- shift: the Divide gesture as a function ----------------------------------------------------


def three_in_a_row():
    _library, project = build()
    a, b, c = project.steps
    placed = {a.id: (40.0, 40.0), b.id: (340.0, 40.0), c.id: (640.0, 40.0)}
    sizes = {step.id: (NODE_W, NODE_H) for step in project.steps}
    return (a, b, c), placed, sizes


def test_shift_pushes_the_side_past_the_cut_and_snaps_the_distance():
    (_a, _b, c), placed, sizes = three_in_a_row()
    assert shift(placed, sizes, "x", 500.0, 300.0) == {c.id: (944.0, 40.0)}  # 300 → 304


def test_shift_brings_the_near_side_back_for_a_negative_distance():
    (a, b, _c), placed, sizes = three_in_a_row()
    assert shift(placed, sizes, "x", 500.0, -80.0) == {a.id: (-40.0, 40.0), b.id: (260.0, 40.0)}


def test_shift_decides_a_crossed_card_by_its_centre():
    (_a, b, c), placed, sizes = three_in_a_row()
    assert set(shift(placed, sizes, "x", 449.0, 80.0)) == {b.id, c.id}  # centre 450 is past
    assert set(shift(placed, sizes, "x", 450.0, 80.0)) == {c.id}  # on the cut is not


def test_shift_moves_only_the_named_steps_and_along_y():
    (a, _b, _c), placed, sizes = three_in_a_row()
    assert shift(placed, sizes, "x", 9999.0, 80.0, only={a.id}) == {a.id: (120.0, 40.0)}
    down = shift(placed, sizes, "y", 50.0, 120.0)
    assert down == {i: (x, y + 120.0) for i, (x, y) in placed.items()}
    assert shift(placed, sizes, "x", 0.0, 3.0) == {}  # snaps to nothing


# -- measuring, and the map ---------------------------------------------------------------------


def key_of(step):
    return step.title


def test_measure_reports_waves_bounds_gaps_and_overlaps():
    library, project = chain_of("A", "B", "C")
    a, b, _c = project.steps
    geometry = measure(library, project, key_of=key_of)
    assert [card.wave for card in geometry.cards] == [1, 2, 3]
    assert geometry.bounds == (40.0, 40.0, 820.0, 76.0)
    assert [pitches(lane, H_GAP, H_PITCH) for lane in geometry.columns] == [None, 1.0, 1.0]
    assert len(geometry.rows) == 1 and geometry.overlaps == ()
    assert [wave.steps for wave in geometry.waves] == [(a.id,), (b.id,), (_c.id,)]

    library.set_module_data(b.id, "project_editor", write_position(40.0, 40.0))  # onto A
    geometry = measure(library, project, key_of=key_of)
    assert geometry.overlaps == ((a.id, b.id),)
    data = as_json(geometry)
    assert data["columns"]["pitch"] == H_PITCH and data["steps"][0]["key"] == "A"
    assert data["overlaps"] == [[a.id, b.id]]
    said = geometry_text(geometry)
    assert "overlaps: A x B" in said and "2 columns x 1 rows" in said
    assert geometry_text(measure(library, Project(title="Empty"), key_of=key_of)) == "no steps"


def test_the_map_puts_each_key_in_its_lane_cell_and_spans_wide_cards():
    library, project = chain_of("A", "B", "C")
    a, b, c = project.steps
    library.set_module_data(a.id, "project_editor", write_position(40.0, 40.0))
    library.set_module_data(b.id, "project_editor", write_position(340.0, 40.0, (500.0, 76.0)))
    library.set_module_data(c.id, "project_editor", write_position(920.0, 40.0))
    (line,) = map_text(measure(library, project, key_of=key_of)).splitlines()
    assert line.index("A") == 0 and line.index("B") == 8 and line.index("C") == 24
    assert "B-------" in line

    library.set_module_data(c.id, "project_editor", write_position(940.0, 40.0))  # two empty
    library.set_module_data(b.id, "project_editor", write_position(40.0, 40.0))  # onto A
    (line,) = map_text(measure(library, project, key_of=key_of)).splitlines()
    assert line.startswith("A/B") and line.index("C") == 24


def test_the_map_is_the_same_before_and_after_a_tidy():
    library, project, _steps = braided()
    before = measure(library, project, key_of=key_of)
    for step_id, (x, y) in tidy(project, positions(library, project)).items():
        library.set_module_data(step_id, "project_editor", write_position(x, y))
    after = measure(library, project, key_of=key_of)
    assert map_text(before) == map_text(after) == map_text(after)
    assert len(map_text(after).splitlines()) == len(after.rows)
    for card in after.cards:
        assert card.key in map_text(after)
