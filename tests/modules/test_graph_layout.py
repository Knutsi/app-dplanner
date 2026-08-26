"""Where a node goes when nobody has placed it.

No ``qapp`` fixture: the placement rules are plain functions over the model, which is the
whole reason they live in their own file.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.modules.project_editor.layout import auto_positions, depths, positions
from dplanner.modules.project_editor.positions import GRID, read_position, write_position


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
