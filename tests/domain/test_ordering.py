"""In what order a project's steps can be done.

No ``qapp`` fixture: the walk is a plain function over the model, which is the whole reason
it lives in the domain rather than in the canvas that first needed it.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import depths, ports, ready, topological_order, upstream, waves


def build(*titles):
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in titles:
        library.add_child(project.id, Step(title=title))
    return library, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def link(library, project, waiter, source):
    """``waiter`` waits on ``source``."""
    step = by_title(project, waiter)
    waiting = [*step.edges.get("requires", []), by_title(project, source).id]
    SetEdgesCommand(step.id, "requires", waiting).redo(library)


def titles(steps):
    return [step.title for step in steps]


def test_a_chain_comes_out_in_order():
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    assert titles(topological_order(library, project)) == ["A", "B", "C"]
    assert [titles(wave) for wave in waves(library, project)] == [["A"], ["B"], ["C"]]


def test_independent_steps_share_a_wave():
    """Nothing waits on anything, so everything can be started now."""
    library, project = build("A", "B", "C")
    assert [titles(wave) for wave in waves(library, project)] == [["A", "B", "C"]]
    assert titles(ready(library, project)) == ["A", "B", "C"]


def test_a_join_waits_for_the_longer_arm():
    """A diamond: D waits on B and C, C waits on B. D belongs after C, not beside it."""
    library, project = build("A", "B", "C", "D")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    link(library, project, "D", "B")
    link(library, project, "D", "C")
    assert [titles(wave) for wave in waves(library, project)] == [["A"], ["B"], ["C"], ["D"]]


def test_nothing_comes_before_what_it_waits_on():
    """The property that makes it a topological sort, asserted as the property."""
    library, project = build("A", "B", "C", "D", "E")
    link(library, project, "C", "A")
    link(library, project, "D", "C")
    link(library, project, "D", "B")
    link(library, project, "E", "D")

    order = topological_order(library, project)
    position = {step.id: index for index, step in enumerate(order)}
    for step in project.steps:
        for waited_on in step.edges.get("requires", []):
            assert position[waited_on] < position[step.id]


def test_the_order_is_stable_across_reads():
    """A sort that reshuffled between two reads would be useless in a diff."""
    library, project = build("A", "B", "C")
    link(library, project, "C", "A")
    first = titles(topological_order(library, project))
    assert titles(topological_order(library, project)) == first


def test_an_unrelated_edit_does_not_reorder_anything():
    library, project = build("A", "B", "C")
    link(library, project, "C", "A")
    before = titles(topological_order(library, project))
    library.set_field(by_title(project, "B").id, "title", "B renamed")
    after = [s.title for s in topological_order(library, project)]
    assert [t.replace("B renamed", "B") for t in after] == before


def test_ties_break_on_the_project_order():
    """Two steps at the same depth come out in the order the project lists them."""
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    link(library, project, "C", "A")
    assert titles(waves(library, project)[1]) == ["B", "C"]


def test_an_empty_project_has_no_waves():
    library, project = build()
    assert waves(library, project) == []
    assert ready(library, project) == []
    assert depths(library, project) == {}


def test_every_step_carries_its_index_and_its_wave():
    """The index is the position in the order; the wave is what it can be started with."""
    from dplanner.domain.ordering import placed

    library, project = build("A", "B", "C", "D")
    link(library, project, "C", "A")
    link(library, project, "D", "C")

    found = placed(library, project)
    assert [(p.index, p.wave, p.step.title) for p in found] == [
        (1, 1, "A"),
        (2, 1, "B"),
        (3, 2, "C"),
        (4, 3, "D"),
    ]


def test_the_index_matches_the_flat_order():
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    from dplanner.domain.ordering import placed

    assert [p.step for p in placed(library, project)] == topological_order(library, project)


# -- upstream: the whole cone behind a step -----------------------------------------


def test_upstream_gathers_the_whole_chain_in_project_order():
    library, project = build("A", "B", "C", "D")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    assert titles(upstream(library, project, by_title(project, "C").id)) == ["A", "B"]
    assert titles(upstream(library, project, by_title(project, "A").id)) == []


def test_upstream_merges_two_branches_and_never_repeats_one():
    """A diamond: D waits on B and C, both of which wait on A."""
    library, project = build("A", "B", "C", "D")
    link(library, project, "B", "A")
    link(library, project, "C", "A")
    link(library, project, "D", "B")
    link(library, project, "D", "C")
    assert titles(upstream(library, project, by_title(project, "D").id)) == ["A", "B", "C"]


def test_upstream_excludes_the_step_itself():
    library, project = build("A", "B")
    link(library, project, "B", "A")
    assert by_title(project, "B") not in upstream(library, project, by_title(project, "B").id)


def test_ports_count_every_kind_of_edge_between_the_steps_given():
    first, second, third = Step(title="a"), Step(title="b"), Step(title="c")
    second.edges["requires"] = [first.id]
    third.edges["relates"] = [second.id]
    assert ports([first, second, third]) == {
        first.id: (False, True),
        second.id: (True, True),
        third.id: (True, False),
    }


def test_an_edge_to_a_step_that_is_not_there_connects_nothing():
    """The canvas draws no arrow for it, so no socket should claim one."""
    first, second = Step(title="a"), Step(title="b")
    second.edges["requires"] = [first.id]
    assert ports([second]) == {second.id: (False, False)}
