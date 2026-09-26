"""Reality, simulated: a team works a plan day by day, and things happen to the plan.

The executor is deliberately the model's own scheduler run against the *true* effort of
each step: the same two pools, the same "longest remaining chain first" priority
(``domain/schedule.py``'s ``chain_tails``), the same milestones-in-sequence rule
(``stretches``), with time continuous inside a working day. So when the true effort equals
the estimate and nothing happens to the plan (*By the book*), whatever gap opens between the
forecast and what happens is the model's own doing, and every other scenario breaks exactly
one assumption on top of that.

Nothing here reads the model or the recorder: this is what happened, not what DPlanner
wrote down about it. It is the HTML prototype's world, step for step, so a scenario and a
seed play the same days in both (``tests/modules/test_time_simulation.py`` holds it to the
prototype's frames).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.progression import BLOCKED, DONE, IN_PROGRESS
from dplanner.domain.schedule import (
    SATURDAY,
    chain_tails,
    stretches,
    working_days_after,
)
from dplanner.modules.time_estimates.schedule import FocusChange
from dplanner.modules.time_estimates.simulation.frames import Plan, StepState
from dplanner.modules.time_estimates.simulation.rng import choose, lognormal, rng, seed_of
from dplanner.modules.time_estimates.simulation.timeline import Played, Timeline

PENDING = "pending"
EPSILON = 1e-9
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class BudgetChange:
    """A re-budget ``after`` days since work began: this team, and this focus if given."""

    after: int
    humans: int
    agents: int
    efficiency: float | None = None


@dataclass(frozen=True)
class Block:
    """The longest-running step blocked ``after`` days since work began, for ``days``
    working days."""

    after: int
    days: int


@dataclass(frozen=True)
class WorldParams:
    seed: int = 7
    human_bias: float = 1.0  # True effort ÷ estimate for human steps, on average.
    agent_bias: float = 1.0
    noise: float = 0.0  # How widely each step's own luck spreads.
    unestimated_effort: float = 1.0  # True days of a step nobody sized.
    focus: float | None = None  # The focus people really give; None is what the plan says.
    agent_load: float = 0.0  # Share of a person's day each running agent step takes.
    scope_per_week: float = 0.0  # New steps per week, into the stretch being worked.
    reestimate_every: int = 0  # Working days between re-estimates; 0 is never.
    reestimate_factor: float = 1.5
    budgets: tuple[BudgetChange, ...] = ()
    block: Block | None = None
    work_ahead: bool = False  # Idle people start the next milestone's ready work.
    dated: bool = True  # The plan has a start date stored.
    lead: int = 3  # Days shown before work begins.
    tail: int = 5  # Days shown after the last step lands.
    max_days: int = 400


DEFAULT_WORLD = WorldParams()

_ADDED_VERBS = ("handle", "support", "fix", "cover")
_ADDED_OBJECTS = ("an edge case", "a second format", "the empty state", "an old import",
                  "a review comment")  # fmt: skip


def run(start: Plan, params: WorldParams, begin: date) -> Timeline:
    return _World(start, params, begin).play()


def _days(step: StepState) -> float | None:
    return None if step.off else step.estimate


def _number(value: float) -> str:
    """A number as the prototype's events print one: ``1``, ``0.25``."""
    return f"{value:g}"


def _key(step: StepState) -> str:
    return f"S{step.number}"


class _World:
    def __init__(self, start: Plan, params: WorldParams, begin: date) -> None:
        self._params = params
        self._begin = begin
        self._title = start.title
        self._steps = [replace(step, status=PENDING) for step in start.steps]
        self._state = replace(start.state, start=begin if params.dated else None)
        self._today = begin
        self._effort: dict[str, float] = {}
        self._progress: dict[str, float] = {}
        self._blocked_until: dict[str, date] = {}
        self._finished: dict[str, date] = {}
        humans, agents = start.state.team
        self._humans: list[str | None] = [None] * humans
        self._agents: list[str | None] = [None] * agents
        self._random = rng(seed_of(params.seed, "events"))
        self._events: list[str] = []
        # The plan's shape, for the model's own stretches and chains to be read off.
        self._shape = Library()
        self._project = Project(title=start.title)
        self._shape.add_child(self._shape.id, self._project)
        for step in self._steps:
            self._shape.add_child(self._project.id, Step(node_id=step.id, title=step.title))
        for step in self._steps:
            self._shape.set_edges(step.id, "requires", list(step.requires))
        # Reality is fixed before anyone re-estimates: a new estimate is learning, not a
        # change.
        for step in self._steps:
            self._effort_of(step)

    def play(self) -> Timeline:
        days: list[Played] = []
        workday = 0
        done_on: date | None = None
        day = self._begin - timedelta(days=self._params.lead)
        while (day - self._begin).days <= self._params.max_days:
            self._events = []
            self._today = day
            if day >= self._begin:
                self._scheduled((day - self._begin).days, day)
                if day.weekday() < SATURDAY:
                    workday += 1
                    if workday > 1:
                        self._change_plan(day, workday)
                    self._work(day)
            days.append(Played(day, self._state, tuple(self._steps), tuple(self._events)))
            if done_on is None and all(step.status == DONE for step in self._steps):
                done_on = day
            if done_on is not None and day >= done_on + timedelta(days=self._params.tail):
                break
            day += _ONE_DAY
        return Timeline(self._title, tuple(days), self._begin, dict(self._finished))

    # -- the plan changing under the team ------------------------------------------------------

    def _find(self, step_id: str) -> StepState:
        return next(step for step in self._steps if step.id == step_id)

    def _store(self, step: StepState) -> StepState:
        at = next(index for index, held in enumerate(self._steps) if held.id == step.id)
        self._steps[at] = step
        return step

    def _set_status(self, step_id: str, status: str) -> StepState:
        """A status, dated as DPlanner's aspect dates one: ``since`` when it changes,
        ``started`` the first time it goes in progress."""
        was = self._find(step_id)
        return self._store(
            replace(
                was,
                status=status,
                since=self._today if status != was.status else was.since,
                started=self._today
                if status == IN_PROGRESS and was.started is None
                else was.started,
            )
        )

    def _scheduled(self, offset: int, day: date) -> None:
        for change in (one for one in self._params.budgets if one.after == offset):
            was = self._state.efficiency
            efficiency = change.efficiency if change.efficiency is not None else was
            self._state = replace(
                self._state,
                team=(change.humans, change.agents),
                efficiency=efficiency,
                efficiency_was=FocusChange(day, was)
                if efficiency != was
                else self._state.efficiency_was,
            )
            self._humans = _resized(self._humans, change.humans)
            self._agents = _resized(self._agents, change.agents)
            people = f"{change.humans} {'person' if change.humans == 1 else 'people'}"
            agents = f"{change.agents} agent{'' if change.agents == 1 else 's'}"
            focus = (
                f" at {math.floor(change.efficiency * 100 + 0.5)}% focus"
                if change.efficiency is not None
                else ""
            )
            self._events.append(f"the team becomes {people} + {agents}{focus}")
        block = self._params.block
        if block is not None and offset == block.after:
            tails = self._tails()
            running = [held for held in (*self._humans, *self._agents) if held is not None]
            running.sort(key=lambda held: -tails.get(held, 0.0))
            if running:
                critical = running[0]
                self._release(critical)
                self._blocked_until[critical] = working_days_after(day, block.days + 1)
                step = self._set_status(critical, BLOCKED)
                self._events.append(
                    f"{_key(step)} {step.title} is blocked for {block.days} working days"
                )
        for step_id, until in list(self._blocked_until.items()):
            if until <= day:
                del self._blocked_until[step_id]
                status = IN_PROGRESS if self._progress.get(step_id) else PENDING
                step = self._set_status(step_id, status)
                self._events.append(f"{_key(step)} is unblocked")

    def _change_plan(self, day: date, workday: int) -> None:
        current = self._current_stretch()
        if current is None:
            return
        milestone, members = current
        params = self._params
        if params.scope_per_week and self._random() < params.scope_per_week / 5:
            agent = self._random() < 0.7
            step_id = f"added-{len(self._steps) + 1}"
            work = [step for step in members if milestone is None or step.id != milestone.id]
            after = choose(self._random, work) if work else None
            title = f"Added: {choose(self._random, _ADDED_VERBS)} "
            title += choose(self._random, _ADDED_OBJECTS)
            estimate = choose(self._random, (0.25, 0.5, 1.0) if agent else (1.0, 2.0, 3.0))
            added = StepState(
                id=step_id,
                number=max(step.number for step in self._steps) + 1,
                title=title,
                requires=(after.id,) if after is not None else (),
                estimate=estimate,
                off=False,
                milestone="",
                agent=agent,
                created=day,
                start=None,
                status=PENDING,
                since=None,
                started=None,
            )
            self._steps.append(added)
            self._shape.add_child(self._project.id, Step(node_id=step_id, title=title))
            self._shape.set_edges(step_id, "requires", list(added.requires))
            self._effort_of(added)
            if milestone is not None:
                requires = (*milestone.requires, step_id)
                self._store(replace(self._find(milestone.id), requires=requires))
                self._shape.set_edges(milestone.id, "requires", list(requires))
            kind = "agent" if agent else "human"
            self._events.append(f"{_key(added)} added ({_number(estimate)}d, {kind})")
        if params.reestimate_every and workday % params.reestimate_every == 0:
            waiting = sorted(
                (step for step in members if step.status == PENDING and _days(step)),
                key=lambda step: -(_days(step) or 0.0),
            )[:3]
            for step in waiting:
                was = step.estimate or 0.0
                estimate = max(0.25, math.floor(was * params.reestimate_factor / 0.25 + 0.5) * 0.25)
                if estimate == was:
                    continue
                self._store(replace(self._find(step.id), estimate=estimate))
                self._events.append(
                    f"{_key(step)} re-estimated {_number(was)}d → {_number(estimate)}d"
                )

    # -- the team working ----------------------------------------------------------------------

    def _effort_of(self, step: StepState) -> float:
        known = self._effort.get(step.id)
        if known is not None:
            return known
        days = _days(step)
        if days is None:
            days = 0.0 if step.off else self._params.unestimated_effort
        bias = self._params.agent_bias if step.agent else self._params.human_bias
        luck = lognormal(rng(seed_of(self._params.seed, step.id)), self._params.noise)
        effort = days * bias * luck
        self._effort[step.id] = effort
        return effort

    def _stretches(self) -> list[tuple[StepState | None, list[StepState]]]:
        """The model's stretches over the plan as it stands, in the world's own records."""
        found = []
        for milestone, members in stretches(self._shape, self._project, self._is_milestone):
            closing = self._find(milestone.id) if milestone is not None else None
            found.append((closing, [self._find(step.id) for step in members]))
        return found

    def _is_milestone(self, step: Step) -> bool:
        return bool(self._find(step.id).milestone)

    def _tails(self) -> dict[str, float]:
        efficiency = self._state.efficiency

        def calendar(step: Step) -> float | None:
            state = self._find(step.id)
            days = _days(state)
            return days if days is None or state.agent else days / efficiency

        found: dict[str, float] = {}
        for _milestone, members in stretches(self._shape, self._project, self._is_milestone):
            found.update(chain_tails(members, calendar))
        return found

    def _current_stretch(self) -> tuple[StepState | None, list[StepState]] | None:
        return next(
            (
                (milestone, members)
                for milestone, members in self._stretches()
                if any(step.status != DONE for step in members)
            ),
            None,
        )

    def _release(self, step_id: str) -> None:
        self._humans = [None if held == step_id else held for held in self._humans]
        self._agents = [None if held == step_id else held for held in self._agents]

    def _land(self, step_id: str, day: date) -> None:
        self._release(step_id)
        self._finished[step_id] = day
        step = self._set_status(step_id, DONE)
        self._events.append(f"{_key(step)} {step.title} done")

    def _work(self, day: date) -> None:
        groups = self._stretches()
        stretch_of = {
            step.id: index for index, (_milestone, members) in enumerate(groups) for step in members
        }
        opens = [milestone.start if milestone is not None else None for milestone, _ in groups]
        tails = self._tails()
        order = {step.id: index for index, step in enumerate(self._steps)}
        known = {step.id for step in self._steps}
        focus = self._params.focus if self._params.focus is not None else self._state.efficiency

        def done(step_id: str) -> bool:
            return self._find(step_id).status == DONE

        def current() -> int:
            # Asked afresh at every moment: a milestone that lands at eleven opens the next
            # one then.
            return next(
                (
                    index
                    for index, (_milestone, members) in enumerate(groups)
                    if any(not done(step.id) for step in members)
                ),
                -1,
            )

        def opened(step: StepState) -> bool:
            asked = opens[stretch_of[step.id]]
            return asked is None or asked <= day

        def eligible(agent: bool) -> StepState | None:
            busy = {held for held in (*self._humans, *self._agents) if held is not None}
            now = current()
            if now < 0:
                return None
            ready = [
                step
                for step in self._steps
                if step.agent == agent
                and step.status not in (DONE, BLOCKED)
                and step.id not in busy
                and (self._params.work_ahead or stretch_of[step.id] == now)
                and opened(step)
                and all(target not in known or done(target) for target in step.requires)
            ]
            ready.sort(key=lambda step: (stretch_of[step.id], -tails[step.id], order[step.id]))
            return ready[0] if ready else None

        def assign() -> None:
            while True:
                moved = False
                for agent in (True, False):
                    for slot in range(len(self._agents if agent else self._humans)):
                        lane = self._agents if agent else self._humans
                        if lane[slot] is not None:
                            continue
                        step = eligible(agent)
                        if step is None:
                            break
                        moved = True
                        if step.status == PENDING:
                            self._set_status(step.id, IN_PROGRESS)
                        if self._effort_of(step) - self._progress.get(step.id, 0.0) <= EPSILON:
                            self._land(step.id, day)
                        else:
                            lane[slot] = step.id
                if not moved:
                    return

        time = 0.0
        for _guard in range(10_000):
            assign()
            busy_agents = sum(1 for held in self._agents if held is not None)
            human = max(
                0.05, focus - (self._params.agent_load * busy_agents) / max(1, len(self._humans))
            )
            busy: list[tuple[str, float]] = [
                *((held, 1.0) for held in self._agents if held is not None),
                *((held, human) for held in self._humans if held is not None),
            ]
            if not busy or time >= 1 - EPSILON:
                return
            step = min(
                1 - time,
                *(
                    (self._effort_of(self._find(held)) - self._progress.get(held, 0.0)) / rate
                    for held, rate in busy
                ),
            )
            for held, rate in busy:
                self._progress[held] = self._progress.get(held, 0.0) + rate * step
            time += step
            for held, _rate in busy:
                if self._effort_of(self._find(held)) - self._progress[held] <= EPSILON:
                    self._land(held, day)


def _resized(lane: Sequence[str | None], size: int) -> list[str | None]:
    kept = list(lane)
    while len(kept) > size:
        free = kept.index(None) if None in kept else len(kept) - 1
        del kept[free]
    while len(kept) < size:
        kept.append(None)
    return kept
