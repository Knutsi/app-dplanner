"""A timeline is reality, day by day — what the plan was at the end of each day, and when
each step really finished. What DPlanner wrote down about it is the recorder's business
(``replay.py``); keeping the two apart is what lets a forecast be held against the truth.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from dplanner.domain.schedule import SATURDAY
from dplanner.modules.time_estimates.simulation.frames import Frame, PlanState, StepState
from dplanner.modules.time_estimates.simulation.rng import rng, seed_of


@dataclass(frozen=True)
class Played:
    """One day of a timeline: the plan as it stood at the day's end, and what happened."""

    day: date
    state: PlanState
    steps: tuple[StepState, ...]
    events: tuple[str, ...]


@dataclass(frozen=True)
class Timeline:
    title: str
    days: tuple[Played, ...]  # One per calendar day, in order.
    begin: date  # The day work began.
    finished: Mapping[str, date]  # The day each step really finished: the truth.

    def frames(self) -> list[Frame]:
        """The days as DPlanner would store them: each day only what changed on it."""
        found: list[Frame] = []
        steps: dict[str, StepState] = {}
        state: PlanState | None = None
        order: tuple[str, ...] = ()
        for played in self.days:
            now = tuple(step.id for step in played.steps)
            changed = tuple(step for step in played.steps if steps.get(step.id) != step)
            found.append(
                Frame(
                    day=played.day,
                    plan=played.state if played.state != state else None,
                    steps=changed,
                    order=now if now != order else None,
                )
            )
            steps = {step.id: step for step in played.steps}
            state, order = played.state, now
        return found

    def index_of(self, day: date) -> int | None:
        return next((at for at, played in enumerate(self.days) if played.day == day), None)


Cadence = Literal["weekdays", "daily", "twice-weekly", "sparse"]

# Which days the window was open, so the recorder ran.
CADENCES: tuple[tuple[Cadence, str], ...] = (
    ("weekdays", "every working day"),
    ("daily", "every day, weekends too"),
    ("twice-weekly", "Mondays and Thursdays"),
    ("sparse", "one day in three, at random"),
)


def recorder_ran(cadence: Cadence, day: date, seed: int) -> bool:
    working = day.weekday() < SATURDAY
    if cadence == "daily":
        return True
    if cadence == "weekdays":
        return working
    if cadence == "twice-weekly":
        return day.weekday() in (0, 3)
    # The prototype names a day by its count since 1970; its luck is keyed on that.
    return working and rng(seed_of(seed, f"record-{(day - date(1970, 1, 1)).days}"))() < 1 / 3
