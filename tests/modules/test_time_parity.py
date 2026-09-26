"""The Time tab's model against the HTML prototype it was designed in, day by day.

``tests/fixtures/time/parity.json.gz`` is every scenario of the prototype's simulator
(``docs/exploration/time-estimation-2`` on branch ``agent/time-estimation-2``) over three
seeds, exported by its ``deno task export-parity``: each day's changes as DPlanner stores
them, and the forecast the prototype's adopted model made that evening. Each run is
replayed into one library through the real aspect writers (``simulation/frames.py``), and
on every day the prototype forecast, the Python model must say the same — each stretch's
milestone, when its work began, where it lands and what it lands on each date.

Regenerate the fixture after a change to the prototype's model, on its branch:
``deno task export-parity local/parity.json.gz``, then copy it here.
"""

import gzip
import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.progression import DONE
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import enabled as estimate_enabled
from dplanner.modules.estimation.aspect import read as estimated_days
from dplanner.modules.estimation.aspect import write as write_estimate
from dplanner.modules.estimation.schedule import start_of, write_start
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import read as milestone_label
from dplanner.modules.step_milestone.aspect import write as write_label
from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
from dplanner.modules.step_status.aspect import read as step_status
from dplanner.modules.step_status.aspect import read_since, read_started
from dplanner.modules.step_status.aspect import write as write_status
from dplanner.modules.time_estimates.progress import Snapshot, take
from dplanner.modules.time_estimates.schedule import (
    FocusChange,
    read_efficiency,
    read_start,
    read_team,
    schedule_facts,
)
from dplanner.modules.time_estimates.simulation.frames import (
    Frame,
    PlanState,
    StepState,
    apply,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "time" / "parity.json.gz"


@cache
def runs() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = json.loads(gzip.decompress(FIXTURE.read_bytes()))["scenarios"]
    return scenarios


# -- the writers the composition root would hand in --------------------------------------------


def _estimate(step: Step, state: StepState, today: date) -> tuple[str, dict[str, Any]]:
    previous = step.module_data.get(ESTIMATION_ID)
    entry = write_estimate(state.estimate, on=not state.off, previous=previous, today=today)
    return ESTIMATION_ID, entry


def _status(step: Step, state: StepState, today: date) -> tuple[str, dict[str, Any]]:
    return STATUS_ID, write_status(
        state.status, today=today, previous=step.module_data.get(STATUS_ID)
    )


def _milestone(_step: Step, state: StepState, _today: date) -> tuple[str, dict[str, Any]]:
    return MILESTONE_ID, write_label(state.milestone)


def _agent(_step: Step, state: StepState, _today: date) -> tuple[str, dict[str, Any]]:
    return AGENT_ID, write_state(state.agent)


def _project_start(_project: Project, plan: PlanState, _today: date) -> tuple[str, dict[str, Any]]:
    return ESTIMATION_ID, write_start(plan.start)


STEP_WRITERS = (_estimate, _status, _milestone, _agent)
PLAN_WRITERS = (_project_start,)


# -- the fixture's days as frames ----------------------------------------------------------------


def _day(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def _step_state(raw: dict[str, Any]) -> StepState:
    return StepState(
        id=raw["id"],
        number=raw["number"],
        title=raw["title"],
        requires=tuple(raw["requires"]),
        estimate=raw["estimate"],
        off=raw["off"],
        milestone=raw["milestone"] or "",
        agent=raw["agent"],
        created=_day(raw["created"]),
        start=_day(raw["start"]),
        status=raw["status"],
        since=_day(raw["since"]),
        started=_day(raw["started"]),
    )


def _frame(raw: dict[str, Any]) -> Frame:
    plan = raw.get("plan")
    was = plan["efficiencyWas"] if plan else None
    return Frame(
        day=date.fromisoformat(raw["day"]),
        plan=PlanState(
            start=_day(plan["start"]),
            efficiency=plan["efficiency"],
            team=(plan["team"][0], plan["team"][1]),
            efficiency_was=FocusChange(date.fromisoformat(was["until"]), was["efficiency"])
            if was
            else None,
        )
        if plan
        else None,
        steps=tuple(_step_state(step) for step in raw.get("steps", [])),
        order=tuple(raw["order"]) if "order" in raw else None,
    )


# -- the model, read as the window reads it ------------------------------------------------------


def _forecast(library: Library, project: Project, day: date) -> Snapshot | None:
    humans, agents = read_team(project)
    return take(
        library,
        project,
        estimated_days,
        agent_enabled,
        step_status,
        read_since,
        humans=humans,
        agents=agents,
        start=start_of(project, day),
        efficiency=read_efficiency(project),
        is_milestone=lambda step: bool(milestone_label(step)),
        start_for=read_start,
        today=day,
        # The prototype's frames are each day at its end.
        facts=schedule_facts(
            project,
            day,
            is_agent=agent_enabled,
            status_for=step_status,
            since_for=read_since,
            is_marker=lambda step: not estimate_enabled(step),
            day_over=True,
        ),
    )


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
    library = Library()
    project = Project(title=f"{run['scenario']} {run['seed']}")
    library.add_child(library.id, project)
    forecasts: list[Snapshot] = []
    for raw in run["days"]:
        frame = _frame(raw)
        apply(library, project, frame, STEP_WRITERS, PLAN_WRITERS)
        for state in frame.steps:  # The status aspect dated each change as the world did.
            step = project.step(state.id)
            assert step is not None
            assert (read_since(step), read_started(step)) == (state.since, state.started)
        if "forecast" in raw:
            said = _forecast(library, project, frame.day)
            assert said is not None, frame.day
            assert raw["forecast"] == _as_exported(said), f"{run['scenario']} on {frame.day}"
            forecasts.append(said)
    return project, forecasts


def _landed(project: Project) -> date:
    """When the work really landed: the last day a step with work was marked done."""
    return max(
        since
        for step in project.steps
        if estimate_enabled(step)
        and step_status(step) == DONE
        and (since := read_since(step)) is not None
    )


@pytest.mark.parametrize("run", runs(), ids=lambda run: f"{run['scenario']}-{run['seed']}")
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
