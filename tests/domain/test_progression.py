"""What can be launched right now, given the graph and the stored statuses.

No ``qapp`` fixture, like ``test_ordering.py``: the walk is a plain function over the
model. Statuses arrive as a function built from a dict — the same shape the composition
root wires in, and the same trick ``test_schedule.py`` plays with ``days_of``.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.domain.ordering import ready
from dplanner.domain.progression import estimated_progress, progression


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


def status_of(statuses):
    """A ``status_for`` from a dict of titles, absent meaning pending."""
    return lambda step: statuses.get(step.title, "pending")


def titles(steps):
    return [step.title for step in steps]


def diamond():
    """A splits into B and C, joining at D — the graph that tells serial from parallel."""
    product, project = build("A", "B", "C", "D")
    link(product, project, "B", "A")
    link(product, project, "C", "A")
    link(product, project, "D", "B")
    link(product, project, "D", "C")
    return product, project


def test_with_nothing_done_the_frontier_is_the_first_wave():
    """The graph-only answer and this one agree exactly when no status is stored."""
    product, project = diamond()
    found = progression(product, project, status_of({}))
    assert titles(row.step for row in found.ready) == titles(ready(product, project))
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_a_finished_prerequisite_frees_its_dependents():
    product, project = diamond()
    found = progression(product, project, status_of({"A": "done"}))
    assert titles(found.done) == ["A"]
    assert titles(row.step for row in found.ready) == ["B", "C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert found.waiting == ()


def test_the_join_waits_for_both_arms():
    product, project = diamond()
    found = progression(product, project, status_of({"A": "done", "B": "done"}))
    assert titles(row.step for row in found.ready) == ["C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert [titles(c.after) for c in found.upcoming] == [["C"]]


def test_a_running_prerequisite_keeps_its_dependents_one_move_out():
    product, project = diamond()
    found = progression(product, project, status_of({"A": "in-progress"}))
    assert titles(found.running) == ["A"]
    assert found.ready == ()
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_a_blocked_prerequisite_still_counts_as_on_the_board():
    """The stalled lane stays visible; its queue must not churn away behind it."""
    product, project = diamond()
    found = progression(product, project, status_of({"A": "blocked"}))
    assert titles(found.attention) == ["A"]
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_out_of_order_completion_is_honoured_not_refused():
    """The graph gates launching, not recording: D done with A pending is D done."""
    product, project = diamond()
    found = progression(product, project, status_of({"D": "done"}))
    assert titles(found.done) == ["D"]
    assert titles(row.step for row in found.ready) == ["A"]
    assert found.percent == 25.0


def test_an_unknown_status_word_reads_as_pending():
    product, project = build("A")
    found = progression(product, project, status_of({"A": "on-fire"}))
    assert titles(row.step for row in found.ready) == ["A"]


def test_the_frontier_ranks_by_what_finishing_unlocks():
    """A feeds a chain of three, D feeds one step: A comes first. F unlocks nothing."""
    product, project = build("A", "B", "C", "D", "E", "F")
    link(product, project, "B", "A")
    link(product, project, "C", "B")
    link(product, project, "E", "D")
    found = progression(product, project, status_of({}))
    assert [(row.step.title, row.unlocks) for row in found.ready] == [("A", 2), ("D", 1), ("F", 0)]


def test_a_done_dependent_is_walked_through_but_not_counted():
    product, project = build("A", "B", "C")
    link(product, project, "B", "A")
    link(product, project, "C", "B")
    found = progression(product, project, status_of({"B": "done"}))
    launchable = next(row for row in found.ready if row.step.title == "A")
    assert launchable.unlocks == 1  # C still waits on A through done B; B itself does not count.


def test_unlock_ties_keep_the_project_order():
    product, project = build("A", "B", "C")
    link(product, project, "C", "A")
    link(product, project, "C", "B")
    found = progression(product, project, status_of({}))
    assert titles(row.step for row in found.ready) == ["A", "B"]


def test_every_step_lands_in_exactly_one_partition():
    product, project = diamond()
    found = progression(
        product, project, status_of({"A": "done", "B": "in-progress", "C": "blocked"})
    )
    assert found.total == 4
    assert titles(found.done) == ["A"]
    assert titles(found.running) == ["B"]
    assert titles(found.attention) == ["C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert found.ready == () and found.waiting == ()


def test_percent_counts_done_against_everything():
    product, project = diamond()
    found = progression(product, project, status_of({"A": "done", "B": "done"}))
    assert found.percent == 50.0


def test_an_empty_project_is_zero_percent_and_empty_everywhere():
    product, project = build()
    found = progression(product, project, status_of({}))
    assert found.total == 0
    assert found.percent == 0.0
    assert found.done == found.running == found.attention == found.waiting == ()
    assert found.ready == () and found.upcoming == ()


def test_estimated_progress_weighs_the_done_work():
    product, project = build("A", "B", "C")
    found = progression(product, project, status_of({"A": "done"}))
    days = {"A": 2.0, "B": 3.0}  # C is unestimated: it contributes to neither number.
    assert estimated_progress(found, lambda step: days.get(step.title)) == (2.0, 5.0)


def test_estimated_progress_is_none_when_nothing_is_sized():
    product, project = build("A", "B")
    found = progression(product, project, status_of({}))
    assert estimated_progress(found, lambda _step: None) is None
