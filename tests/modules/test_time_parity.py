"""The Time tab's model against the HTML prototype it was designed in, day by day.

Each exported run (``time_helpers.py`` says where the fixture comes from) is replayed into
one library through the composition root's own writers (``simulation/replay.py``), and on
every day the prototype forecast, the Python model must say the same — each stretch's
milestone, when its work began, where it lands and what it lands on each date.
"""

from datetime import date
from typing import Any

import pytest
from tests.modules.time_helpers import frame_of, run_id, runs

from dplanner.domain.model import Project
from dplanner.domain.progression import DONE
from dplanner.modules import _time_readers, _time_writers
from dplanner.modules.step_status.aspect import read_started
from dplanner.modules.time_estimates.progress import Snapshot
from dplanner.modules.time_estimates.simulation.replay import Replay

READERS = _time_readers()


def _as_exported(snapshot: Snapshot) -> list[dict[str, Any]]:
    """A snapshot in the prototype's export shape, so a difference reads as the fixture."""
    return [
        {
            "key": stretch.key,
            "start": stretch.start.isoformat(),
            "finish": stretch.finish.isoformat() if stretch.finish else None,
            "landings": [
                [knot.day.isoformat(), knot.steps, pytest.approx(knot.days)]
                for knot in stretch.landings
            ],
        }
        for stretch in snapshot.stretches
    ]


def _replayed(run: dict[str, Any]) -> tuple[Project, list[Snapshot]]:
    """``run`` written into one library a day at a time and held to the prototype's
    forecast on every day it made one: the project it leaves, and the model's forecasts."""
    replay = Replay(run_id(run), _time_writers(), READERS)
    forecasts: list[Snapshot] = []
    for raw in run["days"]:
        frame = frame_of(raw)
        replay.apply(frame)
        for state in frame.steps:  # The status aspect dated each change as the world did.
            step = replay.project.step(state.id)
            assert step is not None
            assert (READERS.since_for(step), read_started(step)) == (state.since, state.started)
        if "forecast" in raw:
            said = replay.forecast(frame.day)
            assert said is not None, frame.day
            assert raw["forecast"] == _as_exported(said), f"{run_id(run)} on {frame.day}"
            forecasts.append(said)
    return replay.project, forecasts


def _landed(project: Project) -> date:
    """When the work really landed: the last day a step with work was marked done."""
    return max(
        since
        for step in project.steps
        if not READERS.is_marker(step)
        and READERS.status_for(step) == DONE
        and (since := READERS.since_for(step)) is not None
    )


@pytest.mark.parametrize("run", runs(), ids=run_id)
def test_every_day_forecasts_what_the_prototype_did(run: dict[str, Any]) -> None:
    """…and on the last day, every run's forecast is where its work really landed: a plan
    finished late never holds again."""
    project, forecasts = _replayed(run)
    assert forecasts[-1].landing(None) == _landed(project)


def test_by_the_book_reads_its_true_landing_every_day() -> None:
    """Every step done the day the plan had it: no milestone's date moves, nor the whole's,
    from the first day to the last — and each is the day its work really landed."""
    (run,) = (one for one in runs() if (one["scenario"], one["seed"]) == ("by-the-book", 1))
    project, forecasts = _replayed(run)
    said: dict[str, set[date | None]] = {}
    for snapshot in forecasts:
        for stretch in snapshot.stretches:
            said.setdefault(stretch.key, set()).add(stretch.finish)
    assert said and all(len(finishes) == 1 for finishes in said.values()), said
    assert max(finish for (finish,) in said.values() if finish) == _landed(project)
