"""In what order a project's steps can be done.

No ``qapp`` fixture: the walk is a plain function over the model, which is the whole reason
it lives in the domain rather than in the canvas that first needed it.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.domain.ordering import depths, ready, topological_order, waves


def build(*titles):
    product = Product(name="Widget")
    project = Project(title="Discovery")
    product.add_child(product.id, project)
    for title in titles:
        product.add_child(project.id, Step(title=title))
    return product, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def link(product, project, waiter, source):
    """``waiter`` waits on ``source``."""
    step = by_title(project, waiter)
    waiting = [*step.edges.get("requires", []), by_title(project, source).id]
    SetEdgesCommand(step.id, "requires", waiting).redo(product)


def titles(steps):
    return [step.title for step in steps]


def test_a_chain_comes_out_in_order():
    product, project = build("A", "B", "C")
    link(product, project, "B", "A")
    link(product, project, "C", "B")
    assert titles(topological_order(product, project)) == ["A", "B", "C"]
    assert [titles(wave) for wave in waves(product, project)] == [["A"], ["B"], ["C"]]


def test_independent_steps_share_a_wave():
    """Nothing waits on anything, so everything can be started now."""
    product, project = build("A", "B", "C")
    assert [titles(wave) for wave in waves(product, project)] == [["A", "B", "C"]]
    assert titles(ready(product, project)) == ["A", "B", "C"]


def test_a_join_waits_for_the_longer_arm():
    """A diamond: D waits on B and C, C waits on B. D belongs after C, not beside it."""
    product, project = build("A", "B", "C", "D")
    link(product, project, "B", "A")
    link(product, project, "C", "B")
    link(product, project, "D", "B")
    link(product, project, "D", "C")
    assert [titles(wave) for wave in waves(product, project)] == [["A"], ["B"], ["C"], ["D"]]


def test_nothing_comes_before_what_it_waits_on():
    """The property that makes it a topological sort, asserted as the property."""
    product, project = build("A", "B", "C", "D", "E")
    link(product, project, "C", "A")
    link(product, project, "D", "C")
    link(product, project, "D", "B")
    link(product, project, "E", "D")

    order = topological_order(product, project)
    position = {step.id: index for index, step in enumerate(order)}
    for step in project.steps:
        for waited_on in step.edges.get("requires", []):
            assert position[waited_on] < position[step.id]


def test_the_order_is_stable_across_reads():
    """A sort that reshuffled between two reads would be useless in a diff."""
    product, project = build("A", "B", "C")
    link(product, project, "C", "A")
    first = titles(topological_order(product, project))
    assert titles(topological_order(product, project)) == first


def test_an_unrelated_edit_does_not_reorder_anything():
    product, project = build("A", "B", "C")
    link(product, project, "C", "A")
    before = titles(topological_order(product, project))
    product.set_field(by_title(project, "B").id, "title", "B renamed")
    after = [s.title for s in topological_order(product, project)]
    assert [t.replace("B renamed", "B") for t in after] == before


def test_ties_break_on_the_project_order():
    """Two steps at the same depth come out in the order the project lists them."""
    product, project = build("A", "B", "C")
    link(product, project, "B", "A")
    link(product, project, "C", "A")
    assert titles(waves(product, project)[1]) == ["B", "C"]


def test_an_empty_project_has_no_waves():
    product, project = build()
    assert waves(product, project) == []
    assert ready(product, project) == []
    assert depths(product, project) == {}


def test_every_step_carries_its_index_and_its_wave():
    """The index is the position in the order; the wave is what it can be started with."""
    from dplanner.domain.ordering import placed

    product, project = build("A", "B", "C", "D")
    link(product, project, "C", "A")
    link(product, project, "D", "C")

    found = placed(product, project)
    assert [(p.index, p.wave, p.step.title) for p in found] == [
        (1, 1, "A"),
        (2, 1, "B"),
        (3, 2, "C"),
        (4, 3, "D"),
    ]


def test_the_index_matches_the_flat_order():
    product, project = build("A", "B", "C")
    link(product, project, "B", "A")
    from dplanner.domain.ordering import placed

    assert [p.step for p in placed(product, project)] == topological_order(product, project)
