"""The Time tab's simulator: the prototype's world, played in Python, recorded as the window
would record it, and a day of it restored into a library in either direction.

The world is held to the HTML prototype's own frames (``time_helpers.py``), so a scenario
and a seed name the same run in both; the model on top of it is held to the prototype's
forecasts by ``test_time_parity.py``.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from tests.modules.time_helpers import frame_of, run_id, runs

from dplanner.modules import _time_readers, _time_writers
from dplanner.modules.time_estimates.progress import read_history, read_saved
from dplanner.modules.time_estimates.simulation.accuracy import timeline_accuracy
from dplanner.modules.time_estimates.simulation.edits import (
    Budget,
    BudgetEdit,
    rebudget,
    world_budgets,
)
from dplanner.modules.time_estimates.simulation.replay import (
    Replay,
    SavedSpec,
    keep,
    record,
    restore,
)
from dplanner.modules.time_estimates.simulation.sample import SAMPLE_START, sample_plan
from dplanner.modules.time_estimates.simulation.scenarios import (
    SAVED_BY_DEFAULT,
    SCENARIOS,
    scenario_by_id,
)
from dplanner.modules.time_estimates.simulation.timeline import Timeline, recorder_ran
from dplanner.modules.time_estimates.simulation.world import run

MONDAY = SAMPLE_START


def _played(scenario_id: str, seed: int) -> Timeline:
    scenario = scenario_by_id(scenario_id)
    return run(sample_plan(seed), replace(scenario.world, seed=seed), SAMPLE_START)


def _replay() -> Replay:
    return Replay("Simulated", _time_writers(), _time_readers())


# -- the prototype's own days --------------------------------------------------------------------


def test_every_scenario_is_one_the_prototype_plays():
    assert {scenario.id for scenario in SCENARIOS} == {one["scenario"] for one in runs()}


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_a_seed_deals_the_prototypes_plan(seed: int):
    first = next(one for one in runs() if one["seed"] == seed)
    assert sample_plan(seed).steps == frame_of(first["days"][0]).steps


@pytest.mark.parametrize("exported", runs(), ids=run_id)
def test_the_world_plays_each_day_as_the_prototype_did(exported: dict[str, Any]):
    """Every day's changes — statuses and their days, steps added, estimates changed, the
    team re-budgeted — exactly as the prototype's world made them."""
    played = _played(exported["scenario"], exported["seed"])
    assert played.frames() == [frame_of(raw) for raw in exported["days"]]


# -- the model over it ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_by_the_book_forecasts_the_real_landing_every_day(seed: int):
    """The control: every step takes exactly its estimate, so a forecast that moved or
    missed would be the model's own doing."""
    measured = timeline_accuracy(_played("by-the-book", seed), _replay())
    for series in (measured.whole, measured.milestones):
        assert (series.error, series.movement, series.moves) == (0.0, 0, 0)
        assert series.samples > 0


def test_a_late_plan_says_so_and_its_forecast_moves():
    measured = timeline_accuracy(_played("optimistic", 1), _replay())
    assert measured.whole.error > 0 and measured.whole.moves > 0


# -- what DPlanner would have written ------------------------------------------------------------


def test_the_recorder_runs_on_the_days_the_window_was_open():
    week = [MONDAY + timedelta(days=n) for n in range(7)]
    assert [recorder_ran("weekdays", day, 1) for day in week] == [True] * 5 + [False] * 2
    assert all(recorder_ran("daily", day, 1) for day in week)
    assert [day.weekday() for day in week if recorder_ran("twice-weekly", day, 1)] == [0, 3]
    sparse = [day for day in week * 4 if recorder_ran("sparse", day, 1)]
    assert all(day.weekday() < 5 for day in sparse)


def test_a_recording_keeps_every_day_and_writes_rows_on_the_days_it_ran():
    played = _played("by-the-book", 1)
    saved = tuple(SAVED_BY_DEFAULT)
    kept = record(played, _replay(), cadence="twice-weekly", seed=1, saved=saved)
    assert len(kept.days) == len(played.days)
    assert kept.rows and all(row.day.weekday() in (0, 3) for row in kept.rows)
    assert [row.title for row in kept.saved] == [one.title for one in saved]
    assert kept.saved[0].day == played.begin
    assert kept.saved[1].day == played.begin + timedelta(days=21)


def test_any_day_is_restored_in_place_whichever_way_the_day_moves():
    """One project, scrubbed forward and back: each time it holds exactly what the day
    held — steps added since gone again, statuses and their days as they were, the history
    as far as it had been written."""
    played = _played("scope-creep", 1)
    kept = record(
        played, _replay(), cadence="weekdays", seed=1, saved=(SavedSpec(0, "Kickoff", ""),)
    )
    shown = _replay()
    late, early = len(played.days) - 1, played.index_of(played.begin + timedelta(days=4))
    assert early is not None
    for index in (late, early, late, 0):
        restore(shown.library, shown.project, kept.days[index])
        assert keep(shown.project) == kept.days[index]
    restore(shown.library, shown.project, kept.days[early])
    assert len(shown.project.steps) < len(played.days[late].steps)  # Scope crept in later.
    assert [row.day for row in read_history(shown.project)] == [
        row.day for row in kept.rows if row.day <= played.days[early].day
    ]
    assert [row.title for row in read_saved(shown.project)] == ["Kickoff"]


# -- a re-budget from a day ----------------------------------------------------------------------


def test_a_rebudget_replaces_the_days_own_and_one_that_changes_nothing_is_none():
    before = Budget(1, 2, 0.5)
    day = MONDAY + timedelta(days=7)
    edits = rebudget((), day, Budget(2, 2, 0.5), before)
    assert edits == (BudgetEdit(day, Budget(2, 2, 0.5)),)
    assert rebudget(edits, day, Budget(3, 2, 0.5), before) == (BudgetEdit(day, Budget(3, 2, 0.5)),)
    assert rebudget(edits, day, before, before) == ()


def test_the_world_changes_the_team_on_the_day_of_a_rebudget():
    day = MONDAY + timedelta(days=7)
    edits = (BudgetEdit(day, Budget(2, 3, 0.6)),)
    world = replace(
        scenario_by_id("by-the-book").world, seed=1, budgets=world_budgets(edits, MONDAY)
    )
    played = run(sample_plan(1), world, SAMPLE_START)
    at = played.index_of(day)
    assert at is not None
    before, after = played.days[at - 1].state, played.days[at].state
    assert (before.team, before.efficiency) == ((1, 2), 0.5)
    assert (after.team, after.efficiency) == ((2, 3), 0.6)
    assert after.efficiency_was is not None and after.efficiency_was.until == day
    assert any(
        "the team becomes 2 people + 3 agents at 60% focus" in e for e in played.days[at].events
    )
