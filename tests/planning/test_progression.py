"""What can be launched right now, given the graph and the stored statuses.

No ``qapp`` fixture, like ``test_ordering.py``: the walk is a plain function over the
model. Statuses arrive as a function built from a dict of the words on disk, read the way the
composition root reads them (``status.held``) — the same trick ``test_schedule.py`` plays
with ``days_of``.
"""

from datetime import date, timedelta

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import ready
from dplanner.planning.progression import (
    across,
    estimated_progress,
    merge,
    outstanding,
    progression,
)
from dplanner.planning.status import Status, Unknown, Waiting, readiness_of


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


WORDS = {status.value: status for status in Status}


def stored_of(statuses):
    """What each step stores, from a dict of titles to words, absent meaning pending."""

    def stored(step):
        word = statuses.get(step.title, "pending")
        return WORDS[word] if word in WORDS else Unknown(word)

    return stored


def status_of(statuses):
    """A ``status_for`` from a dict of titles to words, as readiness reads it."""
    return readiness_of(stored_of(statuses))


def titles(steps):
    return [step.title for step in steps]


def diamond():
    """A splits into B and C, joining at D — the graph that tells serial from parallel."""
    library, project = build("A", "B", "C", "D")
    link(library, project, "B", "A")
    link(library, project, "C", "A")
    link(library, project, "D", "B")
    link(library, project, "D", "C")
    return library, project


def test_with_nothing_done_the_frontier_is_the_first_wave():
    """The graph-only answer and this one agree exactly when no status is stored."""
    library, project = diamond()
    found = progression(library, project, status_of({}))
    assert titles(found.ready) == titles(ready(library, project))
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_a_finished_prerequisite_frees_its_dependents():
    library, project = diamond()
    found = progression(library, project, status_of({"A": "done"}))
    assert titles(found.done) == ["A"]
    assert titles(found.ready) == ["B", "C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert found.waiting == ()


def test_the_join_waits_for_both_arms():
    library, project = diamond()
    found = progression(library, project, status_of({"A": "done", "B": "done"}))
    assert titles(found.ready) == ["C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert [titles(c.after) for c in found.upcoming] == [["C"]]


def test_a_running_prerequisite_keeps_its_dependents_one_move_out():
    library, project = diamond()
    found = progression(library, project, status_of({"A": "in-progress"}))
    assert titles(found.running) == ["A"]
    assert found.ready == ()
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_a_blocked_prerequisite_still_counts_as_on_the_board():
    """The stalled lane stays visible; its queue must not churn away behind it."""
    library, project = diamond()
    found = progression(library, project, status_of({"A": "blocked"}))
    assert titles(found.attention) == ["A"]
    assert titles(c.step for c in found.upcoming) == ["B", "C"]
    assert titles(found.waiting) == ["D"]


def test_out_of_order_completion_is_honoured_not_refused():
    """The graph gates launching, not recording: D done with A pending is D done."""
    library, project = diamond()
    found = progression(library, project, status_of({"D": "done"}))
    assert titles(found.done) == ["D"]
    assert titles(found.ready) == ["A"]
    assert found.percent == 25.0


def test_an_unknown_status_word_holds_its_step_beside_the_blocked_ones():
    library, project = build("A", "B")
    link(library, project, "B", "A")
    found = progression(library, project, status_of({"A": "on-fire"}))
    assert titles(found.attention) == ["A"] and found.ready == ()
    assert titles(found.upcoming[0].after) == ["A"]  # Not done: B still waits on it.


def test_the_frontier_ranks_by_what_finishing_unlocks():
    """A feeds a chain of three, D feeds one step: A comes first. F unlocks nothing."""
    library, project = build("A", "B", "C", "D", "E", "F")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    link(library, project, "E", "D")
    found = progression(library, project, status_of({}))
    assert [(step.title, found.unlocks[step.id]) for step in found.ready] == [
        ("A", 2),
        ("D", 1),
        ("F", 0),
    ]


def test_a_done_dependent_is_walked_through_but_not_counted():
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    found = progression(library, project, status_of({"B": "done"}))
    a = by_title(project, "A")
    assert found.unlocks[a.id] == 1  # C still waits on A through done B; B itself does not count.


def test_unlock_ties_keep_the_project_order():
    library, project = build("A", "B", "C")
    link(library, project, "C", "A")
    link(library, project, "C", "B")
    found = progression(library, project, status_of({}))
    assert titles(found.ready) == ["A", "B"]


def test_every_step_lands_in_exactly_one_partition():
    library, project = diamond()
    found = progression(
        library, project, status_of({"A": "done", "B": "in-progress", "C": "blocked"})
    )
    assert found.total == 4
    assert titles(found.done) == ["A"]
    assert titles(found.running) == ["B"]
    assert titles(found.attention) == ["C"]
    assert titles(c.step for c in found.upcoming) == ["D"]
    assert found.ready == () and found.waiting == ()


def test_review_and_merge_have_partitions_of_their_own():
    """Finished work a person looks at next: on the board, out of the percent."""
    library, project = build("A", "B", "C", "D", "E", "F")
    found = progression(
        library,
        project,
        status_of(
            {
                "A": "done",
                "B": "in-progress",
                "C": "ready-for-review",
                "D": "ready-to-merge",
                "E": "blocked",
            }
        ),
    )
    assert found.total == 6
    assert titles(found.done) == ["A"] and titles(found.running) == ["B"]
    assert titles(found.review) == ["C"] and titles(found.merge) == ["D"]
    assert titles(found.attention) == ["E"] and titles(found.ready) == ["F"]
    assert found.upcoming == () and found.waiting == ()
    assert round(found.percent, 1) == 16.7  # A alone: review and merge are not done


def test_a_plain_requires_waits_for_done_not_for_review_or_merge():
    """A step waiting on reviewed work is one move away, never ready: nothing starts on
    work nobody has accepted — and nothing on work not merged yet either."""
    for word in ("ready-for-review", "ready-to-merge"):
        library, project = diamond()
        found = progression(library, project, status_of({"A": word}))
        assert found.ready == ()
        assert titles(c.step for c in found.upcoming) == ["B", "C"]
        assert [titles(c.after) for c in found.upcoming] == [["A"], ["A"]]
        assert titles(found.waiting) == ["D"]


def test_outstanding_is_the_one_answer_run_agent_reads():
    """Every prerequisite not done, whatever else it reads — review and merge included."""
    library, project = build("A1", "A2", "A3", "P", "C")
    for source in ("A1", "A2", "A3", "P"):
        link(library, project, "C", source)
    statuses = status_of({"A1": "ready-for-review", "A2": "in-progress", "A3": "done"})
    assert titles(outstanding(library, by_title(project, "C"), statuses)) == ["A1", "A2", "P"]


def test_an_unknown_status_holds_a_step_it_is_never_ready():
    """A word a newer build wrote: guessing pending would launch the step again."""
    library, project = build("A", "C")
    link(library, project, "C", "A")
    found = progression(library, project, status_of({"A": "done", "C": "unknown"}))
    assert "C" not in titles(found.ready)
    assert titles(found.attention) == ["C"]


def test_an_agent_waiting_on_a_person_is_asking_not_running():
    library, project = build("A", "B", "C")
    statuses = status_of({"A": "in-progress", "B": "in-progress", "C": "blocked"})
    found = progression(library, project, statuses, asks_person=lambda s: s.title == "B")
    assert titles(found.running) == ["A"] and titles(found.asking) == ["B"]
    assert titles(found.attention) == ["C"] and found.total == 3
    assert titles(merge([found, found]).asking) == ["B", "B"]


def test_every_group_a_person_acts_on_is_ranked_by_what_it_unlocks():
    """Blocked, review and merge rank like the frontier does; ties keep project order."""
    library, project = build("A", "B", "C", "X", "Y")
    link(library, project, "X", "B")
    link(library, project, "Y", "X")
    for word in ("ready-for-review", "ready-to-merge", "blocked"):
        found = progression(library, project, status_of({"A": word, "B": word, "C": word}))
        by_word = {"ready-for-review": found.review, "ready-to-merge": found.merge}
        ranked = by_word.get(word, found.attention)
        assert titles(ranked) == ["B", "A", "C"]
        assert [found.unlocks[step.id] for step in ranked] == [2, 0, 0]


def test_estimated_progress_counts_review_and_merge_as_not_done():
    library, project = build("A", "B", "C")
    found = progression(
        library, project, status_of({"A": "done", "B": "ready-for-review", "C": "ready-to-merge"})
    )
    assert estimated_progress(found, days_for=lambda _step: 1.0) == (1.0, 3.0)


def test_percent_counts_done_against_everything():
    library, project = diamond()
    found = progression(library, project, status_of({"A": "done", "B": "done"}))
    assert found.percent == 50.0


def test_an_empty_project_is_zero_percent_and_empty_everywhere():
    library, project = build()
    found = progression(library, project, status_of({}))
    assert found.total == 0
    assert found.percent == 0.0
    assert found.done == found.running == found.attention == found.waiting == ()
    assert found.review == found.merge == found.ready == () and found.upcoming == ()
    assert found.asking == ()


def test_estimated_progress_weighs_the_done_work():
    library, project = build("A", "B", "C")
    found = progression(library, project, status_of({"A": "done"}))
    days = {"A": 2.0, "B": 3.0}  # C is unestimated: it contributes to neither number.
    assert estimated_progress(found, days_for=lambda step: days.get(step.title)) == (2.0, 5.0)


def test_estimated_progress_is_none_when_nothing_is_sized():
    library, project = build("A", "B")
    found = progression(library, project, status_of({}))
    assert estimated_progress(found, days_for=lambda _step: None) is None


# -- waits ------------------------------------------------------------------------------------


MONDAY = date(2026, 9, 7)


def held_by_a_wait(wait, statuses, since=None, today=MONDAY):
    """A, then a wait W on A, then B on W: what the board makes of it on ``today``."""
    from dplanner.planning.schedule import wait_status

    library, project = build("A", "W", "B")
    link(library, project, "W", "A")
    link(library, project, "B", "W")
    named = {step.title: step for step in project.steps}
    named["W"].created = "2026-09-01T12:00:00"  # made the week before, not the machine's day
    status = wait_status(
        library,
        stored_of(statuses),
        lambda step: (since or {}).get(step.title),
        lambda step: wait if step is named["W"] else None,
        today,
    )
    found = progression(library, project, readiness_of(status), lambda step: step is not named["W"])
    return found, status(named["W"])


def test_a_wait_is_no_work_and_holds_what_follows_it_until_its_day():
    from dplanner.planning.wait import Wait

    wednesday = MONDAY + timedelta(days=2)
    found, wait = held_by_a_wait(Wait(until=wednesday), {"A": "done"}, today=MONDAY)
    assert wait == Waiting()
    assert titles(found.done) == ["A"] and found.total == 2  # the wait is on no lane
    assert titles(found.waiting) == ["B"] and found.ready == ()
    found, wait = held_by_a_wait(Wait(until=wednesday), {"A": "done"}, today=wednesday)
    assert wait is Status.DONE
    assert titles(found.ready) == ["B"]
    assert found.percent == 50.0  # of the work: A of A and B


def test_a_wait_holds_while_what_it_waits_on_is_not_done():
    from dplanner.planning.wait import Wait

    found, wait = held_by_a_wait(Wait(until=MONDAY), {}, today=MONDAY + timedelta(days=7))
    assert wait == Waiting() and titles(found.ready) == ["A"]
    assert found.unlocks[found.ready[0].id] == 1  # B, and not the wait: it is no work


def test_a_days_wait_is_over_once_its_days_are_waited():
    """Three working days from A's Monday, middle to middle: over on Thursday."""
    from dplanner.planning.wait import Wait

    done = {"A": "done"}
    since = {"A": MONDAY}
    wednesday, thursday = MONDAY + timedelta(days=2), MONDAY + timedelta(days=3)
    assert held_by_a_wait(Wait(days=3.0), done, since, wednesday)[1] == Waiting()
    assert held_by_a_wait(Wait(days=3.0), done, since, thursday)[1] is Status.DONE


# -- several projects, one board ----------------------------------------------------------------


def two_projects():
    """Alpha: A3 waits on A2, A1 on nothing. Beta: B2 and B3 wait on B1, B4 on nothing — so
    finishing B1 frees two, A2 one, and A1 and B4 none."""
    library = Library()
    for name, titles_ in (("Alpha", ("A1", "A2", "A3")), ("Beta", ("B1", "B2", "B3", "B4"))):
        project = Project(title=name)
        library.add_child(library.id, project)
        for title in titles_:
            library.add_child(project.id, Step(title=title))
    alpha, beta = library.projects
    link(library, alpha, "A3", "A2")
    link(library, beta, "B2", "B1")
    link(library, beta, "B3", "B1")
    return library, alpha, beta


def test_ready_across_projects_ranks_by_unlocks_and_ties_go_library_order():
    """What can start anywhere, the step that frees most first — and between two that free
    the same, the earlier project's, then that project's own order."""
    library, alpha, beta = two_projects()
    found = across(library, [alpha, beta], status_of({}))
    assert titles(found.ready) == ["B1", "A2", "A1", "B4"]
    assert titles(c.step for c in found.upcoming) == ["A3", "B2", "B3"]
    assert found.unlocks[found.ready[0].id] == 2


def test_the_board_is_every_step_of_every_project_once():
    library, alpha, beta = two_projects()
    found = across(library, [alpha, beta], status_of({"B1": "ready-for-review", "A1": "done"}))
    assert found.total == len(alpha.steps) + len(beta.steps)
    assert titles(found.done) == ["A1"]
    assert titles(found.review) == ["B1"]


def test_one_progression_merged_is_itself():
    library, project = diamond()
    found = progression(library, project, status_of({"A": "done"}))
    assert merge([found]) == found


def test_nothing_merged_is_an_empty_board():
    found = merge([])
    assert found.total == 0
    assert found.percent == 0.0
