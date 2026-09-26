"""A day of a simulated plan, written into a library as the people on it would have left it.

A :class:`Frame` is one day's changes in the terms DPlanner stores — a step's title, number,
``requires``, estimate, milestone label, agent flag, the day it was made, a milestone's own
start and its status; the project's start and its staffing assumptions. :func:`apply`
writes it with today being the frame's day, **through each owner's own aspect writer**,
handed in as a :data:`StepWriter` because modules never import each other. So the library
afterwards holds what the edits of that day would have: the status aspect stamps its own
``since`` and ``started``, and a forecast read from it is read the way the window reads one.

The parity test replays the HTML prototype's scenarios through it and holds the model to
the prototype's forecasts, day by day.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Any

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.progression import IN_PROGRESS
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    Assumptions,
    FocusChange,
    read_assumptions,
    read_color,
    write_assumptions,
    write_milestone,
)


@dataclass(frozen=True)
class StepState:
    """A step as it stands at the end of a frame's day."""

    id: str
    number: int
    title: str
    requires: tuple[str, ...]
    estimate: float | None
    off: bool  # Its estimate is off: a step that carries no work by design.
    milestone: str  # The milestone label, "" for a step that closes none.
    agent: bool
    created: date | None
    start: date | None  # A milestone's own start date.
    status: str
    since: date | None
    started: date | None


@dataclass(frozen=True)
class PlanState:
    """The project's own settings as they stand at the end of a frame's day."""

    start: date | None
    efficiency: float
    team: tuple[int, int]
    efficiency_was: FocusChange | None


@dataclass(frozen=True)
class Frame:
    """One day: the steps that changed on it, the project's settings where they changed,
    and the project's order of steps where a step was added — each None or empty when
    nothing of the kind moved."""

    day: date
    plan: PlanState | None = None
    steps: tuple[StepState, ...] = ()
    order: tuple[str, ...] | None = None


StepWriter = Callable[[Step, StepState, date], tuple[str, dict[str, Any]]]
"""One owner's entry for a step now in ``state``, written on a day: the module it is
stored under, and the entry — its writer handed the one it replaces, as any edit would."""

PlanWriter = Callable[[Project, PlanState, date], tuple[str, dict[str, Any]]]
"""The same for the project node."""


def apply(
    library: Library,
    project: Project,
    frame: Frame,
    step_writers: Sequence[StepWriter],
    plan_writers: Sequence[PlanWriter],
) -> None:
    """Write ``frame`` into ``project``: new steps where the order puts them, then every
    changed step's links and aspects, then the project's settings. Straight onto the
    library, off any undo stack — a replay is nobody's edit to take back."""
    known = {step.id for step in project.steps}
    arriving = [state for state in frame.steps if state.id not in known]
    if arriving:
        if frame.order is None:
            raise ValueError(f"{frame.day}: steps arrive with no order to place them in")
        order = frame.order
        if [step.id for step in project.steps] != [one for one in order if one in known]:
            raise ValueError(f"{frame.day}: a frame only ever adds steps")
        for state in sorted(arriving, key=lambda state: order.index(state.id)):
            born = Step(
                node_id=state.id, title=state.title, number=state.number, created=_stamp(state)
            )
            AddNodeCommand(project.id, born, order.index(state.id)).redo(library)
    for state in frame.steps:
        step = project.step(state.id)
        assert step is not None
        if tuple(step.edges.get("requires", [])) != state.requires:
            SetEdgesCommand(step.id, "requires", list(state.requires)).redo(library)
        for passing in _through(state, frame.day):
            for step_writer in step_writers:
                module_id, entry = step_writer(step, passing, frame.day)
                SetModuleDataCommand(step.id, module_id, entry).redo(library)
        own = write_milestone(state.start, read_color(step))
        SetModuleDataCommand(step.id, MODULE_ID, own).redo(library)
    if frame.plan is not None:
        for plan_writer in plan_writers:
            module_id, entry = plan_writer(project, frame.plan, frame.day)
            SetModuleDataCommand(project.id, module_id, entry).redo(library)
        stored = read_assumptions(project)
        assumptions = Assumptions(
            efficiency=frame.plan.efficiency,
            palette=stored.palette,
            team=frame.plan.team,
            efficiency_was=frame.plan.efficiency_was,
        )
        SetModuleDataCommand(project.id, MODULE_ID, write_assumptions(assumptions)).redo(library)


def _through(state: StepState, day: date) -> tuple[StepState, ...]:
    """The states a step passed through on ``day``, in turn. A frame is the day's end, so
    work begun and finished within it shows only as finished — but it went in progress
    first, which is when its status stamps ``started``."""
    if state.started == day and state.status != IN_PROGRESS:
        return (replace(state, status=IN_PROGRESS), state)
    return (state,)


def _stamp(state: StepState) -> str:
    """A ``created`` stamp that reads back as the day the step was made, wherever the
    replay runs: midday, local, with no offset."""
    return datetime.combine(state.created, time(12)).isoformat() if state.created else ""
