"""Where a node goes when nobody has placed it.

No ``qapp`` fixture: the placement rules are plain functions over the model, which is the
whole reason they live in their own file. The dependency walk they build on is the domain's
and is tested in ``tests/domain/test_ordering.py``; what is tested here is where a node
ends up on screen.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.domain.ordering import depths
from dplanner.modules.project_editor.layout import auto_positions, positions
from dplanner.modules.project_editor.positions import (
    GRID,
    NODE_H,
    NODE_W,
    read_position,
    write_position,
)
from dplanner.modules.project_editor.sorts import (
    DAY_PX,
    ORIGIN,
    layered_down,
    layered_flow,
    most_connected,
    node_size,
    radial,
    spine,
    timeline,
)


def build():
    product = Product(name="Widget")
    project = Project(title="Discovery")
    product.add_child(product.id, project)
    for title in ("A", "B", "C"):
        product.add_child(project.id, Step(title=title))
    return product, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def test_a_chain_reads_left_to_right():
    product, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(product)
    SetEdgesCommand(c.id, "requires", [b.id]).redo(product)

    found = depths(product, project)
    assert (found[a.id], found[b.id], found[c.id]) == (0, 1, 2)
    placed = auto_positions(product, project)
    assert placed[a.id][0] < placed[b.id][0] < placed[c.id][0]


def test_independent_steps_stack_in_one_column():
    product, project = build()
    placed = auto_positions(product, project)
    xs = {placed[step.id][0] for step in project.steps}
    ys = {placed[step.id][1] for step in project.steps}
    assert len(xs) == 1 and len(ys) == 3


def test_the_longest_chain_wins():
    """A step waiting on two things sits after the later of them, not the earlier."""
    product, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(product)
    SetEdgesCommand(c.id, "requires", [a.id, b.id]).redo(product)
    assert depths(product, project)[c.id] == 2


def test_a_stored_position_wins_over_the_automatic_one():
    product, project = build()
    step = by_title(project, "B")
    product.set_module_data(step.id, "project_editor", write_position(504.0, 304.0))
    placed = positions(product, project)
    assert placed[step.id] == (504.0, 304.0)  # Already on the grid, so stored verbatim.
    assert (
        placed[by_title(project, "A").id]
        == auto_positions(product, project)[by_title(project, "A").id]
    )


def test_positions_snap_and_are_stored_as_floats():
    """FORMAT.md's numeric rule: an int would write as 8 where a reloaded float writes 8.0."""
    entry = write_position(11.0, 3.0)
    assert entry["x"] == 8.0 and entry["y"] == 0.0
    assert isinstance(entry["x"], float)
    assert GRID == 8.0


def test_an_unreadable_position_reads_as_absent():
    """A hand-edited or newer file must not crash the canvas."""
    product, project = build()
    step = project.steps[0]
    product.set_module_data(step.id, "project_editor", {"x": "left", "y": 4})
    assert read_position(step) is None


# -- the sort battery ---------------------------------------------------------------------------
#
# Every sort must be deterministic (same graph, same result — ties break by project order),
# size-aware (spacing follows what size_for answers), and leave no two nodes overlapping.


def braided(flip_edges=False):
    """Two chains that cross, a shared gate, and a loose end — enough shape to tangle."""
    product = Product(name="Widget")
    project = Project(title="Discovery")
    product.add_child(product.id, project)
    steps = {}
    for title in ("a", "b", "c", "d", "e", "f", "g", "loose"):
        step = Step(title=title)
        steps[title] = step
        product.add_child(project.id, step)

    def link(waiter, sources):
        ordered = list(reversed(sources)) if flip_edges else sources
        SetEdgesCommand(steps[waiter].id, "requires", [steps[s].id for s in ordered]).redo(
            product
        )

    link("c", ["b"])
    link("d", ["a"])
    link("e", ["c", "d"])
    link("f", ["d", "c"])
    link("g", ["e", "f"])
    return product, project, steps


def assert_no_overlap(placed, size_for=node_size, steps_by_id=None):
    rects = []
    for step_id, (x, y) in placed.items():
        w, h = size_for(steps_by_id[step_id]) if steps_by_id else (180.0, 56.0)
        rects.append((step_id, x, y, w, h))
    for i, (one, x1, y1, w1, h1) in enumerate(rects):
        for other, x2, y2, w2, h2 in rects[i + 1 :]:
            apart = x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
            assert apart, f"{one} overlaps {other}"


def every_sort(product, project):
    return {
        "flow": layered_flow(product, project),
        "down": layered_down(product, project),
        "spine": spine(product, project),
        "timeline": timeline(product, project),
        "radial": radial(product, project),
    }


def test_every_sort_is_deterministic_and_overlap_free():
    product, project, _steps = braided()
    first = every_sort(product, project)
    again = every_sort(product, project)
    for name, placed in first.items():
        assert placed.keys() == {step.id for step in project.steps}
        assert placed == again[name], f"{name} is not deterministic"
        assert_no_overlap(placed)


def test_edge_list_order_does_not_change_a_sort():
    product, project, steps = braided()
    flipped_product, flipped_project, flipped_steps = braided(flip_edges=True)
    one = every_sort(product, project)
    other = every_sort(flipped_product, flipped_project)
    for name in one:
        by_title = {title: one[name][step.id] for title, step in steps.items()}
        flipped = {title: other[name][step.id] for title, step in flipped_steps.items()}
        assert by_title == flipped, f"{name} depends on edge insertion order"


def test_flow_keeps_left_to_right_depth_order():
    product, project, _steps = braided()
    placed = layered_flow(product, project)
    for step in project.steps:
        for source in step.edges.get("requires", []):
            assert placed[source][0] < placed[step.id][0]


def test_barycenter_untangles_a_crossing():
    product, project = build()
    a, b, c = project.steps
    d = Step(title="D")
    product.add_child(project.id, d)
    # C waits on B and D waits on A: laid in project order the two edges would cross.
    SetEdgesCommand(c.id, "requires", [b.id]).redo(product)
    SetEdgesCommand(d.id, "requires", [a.id]).redo(product)

    placed = layered_flow(product, project)
    same_side = (placed[a.id][1] < placed[b.id][1]) == (placed[d.id][1] < placed[c.id][1])
    assert same_side, "the second column should mirror the first's order"


def test_layered_down_flows_top_to_bottom():
    product, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(product)
    SetEdgesCommand(c.id, "requires", [b.id]).redo(product)
    placed = layered_down(product, project)
    assert placed[a.id][1] < placed[b.id][1] < placed[c.id][1]


def test_spine_lays_the_longest_chain_on_one_line():
    product, project, steps = braided()
    placed = spine(product, project)
    # b → c → e → g is the deepest chain through the first-by-project-order sources.
    chain = [steps[t].id for t in ("b", "c", "e", "g")]
    assert {placed[sid][1] for sid in chain} == {0.0}
    xs = [placed[sid][0] for sid in chain]
    assert xs == sorted(xs)
    off_spine = [sid for sid in placed if sid not in chain]
    assert all(placed[sid][1] != 0.0 for sid in off_spine)


def test_spine_ribs_alternate_sides():
    product, project, _steps = braided()
    placed = spine(product, project)
    sides = {1.0 if y > 0 else -1.0 for _x, y in placed.values() if y != 0.0}
    assert sides == {1.0, -1.0}


def test_timeline_x_follows_earliest_start():
    product, project = build()
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(product)
    days = {a.id: 2.0}
    placed = timeline(product, project, days_for=lambda step: days.get(step.id))

    assert placed[a.id][0] == ORIGIN
    assert placed[c.id][0] == ORIGIN  # nothing to wait on
    assert placed[b.id][0] == ORIGIN + 2.0 * DAY_PX
    assert_no_overlap(placed)


def test_radial_rings_follow_bfs_distance():
    product, project = build()
    a, b, c = project.steps
    d = Step(title="D")
    product.add_child(project.id, d)
    SetEdgesCommand(b.id, "requires", [a.id]).redo(product)
    SetEdgesCommand(c.id, "requires", [a.id]).redo(product)
    SetEdgesCommand(d.id, "requires", [b.id]).redo(product)

    def r(placed, step):
        x, y = placed[step.id]
        cx, cy = x + NODE_W / 2, y + NODE_H / 2  # the node's centre, for the default size
        return (cx**2 + cy**2) ** 0.5

    placed = radial(product, project)  # a is the most connected, so the centre
    assert r(placed, a) < 1e-9
    assert abs(r(placed, b) - r(placed, c)) < 1e-9
    assert r(placed, d) > r(placed, b)

    recentred = radial(product, project, center=d.id)
    assert r(recentred, d) < 1e-9
    assert most_connected(product, project) == a.id


def test_sorts_respect_node_sizes():
    product, project, steps = braided()
    big = steps["c"].id

    def size_for(step):
        return (360.0, 200.0) if step.id == big else (180.0, 56.0)

    by_id = {step.id: step for step in project.steps}
    for sort in (layered_flow, layered_down, spine, timeline):
        placed = sort(product, project, size_for=size_for)
        assert_no_overlap(placed, size_for=size_for, steps_by_id=by_id)
