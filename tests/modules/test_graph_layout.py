"""Where a node goes when nobody has placed it.

No ``qapp`` fixture: the placement rules are plain functions over the model, which is the
whole reason they live in their own file. The dependency walk they build on is the domain's
and is tested in ``tests/domain/test_ordering.py``; what is tested here is where a node
ends up on screen.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import depths
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
    ORIGIN,
    layered_down,
    layered_flow,
    most_connected,
    radial,
    spine,
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
