"""The HTML prototype's scenarios, played out and exported, for the Time tab's model and
simulator to be held to.

``tests/fixtures/time/parity.json.gz`` is every scenario of the prototype's simulator
(``docs/exploration/time-estimation-2`` on branch ``agent/time-estimation-2``) over three
seeds, exported by its ``deno task export-parity``: each day's changes as DPlanner stores
them, and the forecast the prototype's model made that evening. Regenerate it after a change
to the prototype's model, on its branch — ``deno task export-parity local/parity.json.gz`` —
and copy it here.
"""

import gzip
import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from dplanner.modules.time_estimates.schedule import FocusChange
from dplanner.modules.time_estimates.simulation.frames import Frame, PlanState, StepState

FIXTURE = Path(__file__).parent.parent / "fixtures" / "time" / "parity.json.gz"


@cache
def runs() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = json.loads(gzip.decompress(FIXTURE.read_bytes()))["scenarios"]
    return scenarios


def run_id(run: dict[str, Any]) -> str:
    return f"{run['scenario']}-{run['seed']}"


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


def frame_of(raw: dict[str, Any]) -> Frame:
    """One exported day as the frame it records."""
    plan = raw.get("plan")
    state = None
    if plan:
        was = plan["efficiencyWas"]
        state = PlanState(
            start=_day(plan["start"]),
            efficiency=plan["efficiency"],
            team=(plan["team"][0], plan["team"][1]),
            efficiency_was=FocusChange(date.fromisoformat(was["until"]), was["efficiency"])
            if was
            else None,
        )
    return Frame(
        day=date.fromisoformat(raw["day"]),
        plan=state,
        steps=tuple(_step_state(step) for step in raw.get("steps", [])),
        order=tuple(raw["order"]) if "order" in raw else None,
    )
