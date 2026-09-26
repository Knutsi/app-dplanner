"""Waits in the simulated world: a team that really waits for one, and forecasts that hold
to the day — the prototype's ``delay_test.ts``, played through the real aspect writers.

No ``qapp`` fixture: the simulator is Qt-free by rule.
"""

from dataclasses import replace
from datetime import date

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import SATURDAY, Wait, chain_tails, stretches
from dplanner.modules import _time_readers, _time_writers
from dplanner.modules.time_estimates.schedule import stretched
from dplanner.modules.time_estimates.simulation.frames import Plan, StepState
from dplanner.modules.time_estimates.simulation.replay import Replay
from dplanner.modules.time_estimates.simulation.sample import SAMPLE_START, sample_plan
from dplanner.modules.time_estimates.simulation.timeline import Timeline
from dplanner.modules.time_estimates.simulation.world import (
    DEFAULT_WORLD,
    WaitChange,
    insert_wait,
    run,
    wait_id,
)

MADE = date(2026, 10, 12)
WEDNESDAY = date(2026, 11, 4)


def _shape(plan: Plan) -> tuple[Library, Project]:
    library = Library()
    project = Project(title=plan.title)
    library.add_child(library.id, project)
    for state in plan.steps:
        library.add_child(project.id, Step(node_id=state.id, title=state.title))
    for state in plan.steps:
        library.set_edges(state.id, "requires", list(state.requires))
    return library, project


def _held(plan: Plan) -> str:
    """The step of the second milestone's work that its longest chain starts from."""
    library, project = _shape(plan)
    states = {state.id: state for state in plan.steps}
    groups = stretches(library, project, lambda step: bool(states[step.id].milestone))
    (m1, _first), (_m2, members) = groups[0], groups[1]
    assert m1 is not None

    def days(step: Step) -> float | None:
        state = states[step.id]
        return None if state.off else state.estimate

    calendar = stretched(days, lambda step: states[step.id].agent, plan.state.efficiency)
    tails = chain_tails(members, calendar)
    after = [step for step in members if m1.id in states[step.id].requires]
    return max(after, key=lambda step: tails[step.id]).id


def _waited(wait: Wait | None) -> tuple[Timeline, str]:
    """By the book, with the step the second milestone's longest chain starts from made to
    wait on ``MADE``."""
    plan = sample_plan(1)
    held = _held(plan)
    waits = () if wait is None else (WaitChange((MADE - SAMPLE_START).days, held, wait),)
    world = replace(DEFAULT_WORLD, seed=1, unestimated_effort=0.0, waits=waits)
    return run(plan, world, SAMPLE_START), held


def _forecasts(timeline: Timeline, key: str) -> list[tuple[date, date]]:
    """What the model said each working day, at the day's end, of where ``key`` lands."""
    replay = Replay("Waited", _time_writers(), _time_readers())
    found = []
    for played, frame in zip(timeline.days, timeline.frames(), strict=True):
        replay.apply(frame)
        if played.day < timeline.begin or played.day.weekday() >= SATURDAY:
            continue
        said = replay.forecast(played.day)
        landing = said.landing(key) if said is not None else None
        if landing is not None:
            found.append((played.day, landing))
    return found


def _exact_from(timeline: Timeline, day: date, within: int) -> None:
    last = timeline.days[-1].steps
    for step in (one for one in last if one.milestone):
        truth = timeline.finished[step.id]
        for when, said in _forecasts(timeline, step.id):
            if day <= when <= truth:
                off = abs((said - truth).days)
                assert off <= within, f"{step.milestone} on {when}: said {said}, landed {truth}"


def _state(timeline: Timeline, day: date, step_id: str) -> StepState:
    played = timeline.days[timeline.index_of(day) or 0]
    return next(step for step in played.steps if step.id == step_id)


def test_a_wait_is_inserted_before_the_step_it_holds_and_takes_over_what_it_required():
    plan = sample_plan(1)
    held = _held(plan)
    was = next(step for step in plan.steps if step.id == held)
    steps = insert_wait(plan.steps, MADE, held, Wait(days=3.0))
    made = wait_id(MADE, held)
    added = next(step for step in steps if step.id == made)
    assert added.requires == was.requires and added.title == "Wait 3 working days"
    assert next(step for step in steps if step.id == held).requires == (made,)
    assert steps.index(added) == [step.id for step in steps].index(held) - 1
    assert insert_wait(steps, MADE, held, Wait(days=3.0)) == steps  # made once


def test_the_team_waits_the_held_step_starts_no_earlier_than_the_wait_allows():
    timeline, held = _waited(Wait(until=WEDNESDAY))
    started = next(
        played.day
        for played in timeline.days
        if next(step for step in played.steps if step.id == held).status != "pending"
    )
    # It is picked up the moment the wait ends: as the day before Wednesday ends.
    assert started == date(2026, 11, 3)
    wait = _state(timeline, timeline.days[-1].day, wait_id(MADE, held))
    assert (wait.created, bool(wait.requires), wait.wait) == (MADE, True, Wait(until=WEDNESDAY))


def test_by_the_book_with_a_wait_until_wednesday_every_forecast_from_that_day_is_exact():
    timeline, _held_id = _waited(Wait(until=WEDNESDAY))
    _exact_from(timeline, MADE, 0)


def test_by_the_book_with_a_wait_of_days_the_forecast_from_that_day_is_within_a_day():
    timeline, _held_id = _waited(Wait(days=4.0))
    _exact_from(timeline, MADE, 1)


def test_what_if_testing_starts_wednesday_the_milestones_behind_it_move_to_the_day():
    plain, _held_id = _waited(None)
    timeline, _held_id = _waited(Wait(until=WEDNESDAY))
    m2 = [step for step in timeline.days[-1].steps if step.milestone][1].id
    before = dict(_forecasts(plain, m2))[MADE]
    after = dict(_forecasts(timeline, m2))[MADE]
    assert after > before  # M2 moves out
    assert after == timeline.finished[m2]  # to the day it really lands
