"""The garden at Home's foot, as plain state: a plan, told as a garden.

Seeds are steps and the roots between them are links. A seed sprouts only once every seed
it waits on has bloomed — which is the whole of what *ready* means in a plan — and a bloom
sends a pulse down its roots to what it unblocks. Agents, wearing the sparkle every agent
step wears on its card, fly to what is ready, sprinkle it, and it grows and blooms; two work
side by side when two things are ready at once. When everything has bloomed the garden
rests, lets its petals go, and the next season is planted.

Plain data and arithmetic, so the rules are tested without a window: places are fractions
of the garden's width and height (``y`` down, 0 at the top), time is seconds, and
``garden_view.py`` is the only thing that knows pixels, colours or a clock. ``advance``
returns what *happened* — a bloom, a sprout — for the painter's bursts; everything that
*is* can be read straight off the state.
"""

import math
from dataclasses import dataclass, field

from dplanner.framework.motion.curves import Point, cubic, in_out_cubic, span

GROUND_Y = 0.83  # Where the soil is.
HOVER_Y = 0.2  # Where an agent hangs while it works.
PULSE_S = 1.1  # A bloom's pulse, from one seed to the next along a root.
WORK_S = 3.0  # How long an agent sprinkles one seed into a flower.
FIRST_SPROUT_S = 0.8  # How long a new season waits before its first seed is ready.
REST_S = 7.0  # How long a garden in full bloom stays so.
LET_GO_S = 3.2  # Petals away, stems down, seeds again.


# What a seed grows into, and how many petals it has to let go of when the season turns.
PETALS = {"round": 6, "daisy": 11, "tulip": 3, "lotus": 8}


@dataclass(frozen=True)
class Seed:
    x: float
    waits: tuple[int, ...]  # The seeds this one needs in bloom before it can sprout.
    height: float  # How tall it grows, as a fraction of the garden's height.
    style: str  # One of PETALS: the painter's word for its flower.
    milestone: bool = False  # The one the plan ends at: taller, fuller, and it keeps a halo.

    @property
    def petals(self) -> int:
        return PETALS[self.style]


# A small plan: one start, a fan, a join, and a milestone it all leads to.
PLAN = (
    Seed(0.06, (), 0.4, "round"),
    Seed(0.16, (0,), 0.3, "daisy"),
    Seed(0.26, (0,), 0.46, "tulip"),
    Seed(0.37, (1,), 0.34, "round"),
    Seed(0.47, (1, 2), 0.5, "daisy"),
    Seed(0.57, (2,), 0.36, "tulip"),
    Seed(0.67, (3, 4), 0.44, "round"),
    Seed(0.77, (4, 5), 0.32, "daisy"),
    Seed(0.88, (6, 7), 0.56, "lotus", milestone=True),
)
# Where each agent waits for something to be ready at the start of a season.
PERCHES = ((0.05, 0.16), (0.15, 0.1))


@dataclass
class Plant:
    seed: Seed
    stage: str = "seed"  # "seed" waiting, "ready" sprouted, "growing" under an agent, "bloomed".
    growth: float = 0.0
    since: float = 0.0  # When it entered its stage.
    wilt: float = 0.0  # How far through letting go.


@dataclass
class Pulse:
    source: int
    waiter: int
    started: float

    def at(self, t: float) -> float:
        return span(t, self.started, PULSE_S)


@dataclass
class Agent:
    x: float
    y: float
    perch: Point
    phase: float  # So two agents idling do not bob in step.
    state: str = "idle"  # "idle", "flying", "working".
    target: int | None = None
    since: float = 0.0
    flight: tuple[Point, Point, Point, Point] = ((0, 0), (0, 0), (0, 0), (0, 0))
    flight_s: float = 1.0
    heading: float = 0.0  # Which way it last moved: -1 left, 1 right.


@dataclass
class Garden:
    plan: tuple[Seed, ...] = PLAN
    plants: list[Plant] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)
    pulses: list[Pulse] = field(default_factory=list)
    t: float = 0.0
    season: str = "growing"  # "growing", "resting", "letting go".
    since: float = 0.0
    round: int = 0  # Which season this is: the painter deals colours by it.

    def __post_init__(self) -> None:
        if not self.plants:
            self.plants = [Plant(seed) for seed in self.plan]
        if not self.agents:
            self.agents = [
                Agent(x, y, (x, y), phase=index * 2.1) for index, (x, y) in enumerate(PERCHES)
            ]

    # -- what can be read ------------------------------------------------------------------

    def waiters(self, index: int) -> list[int]:
        return [other for other, seed in enumerate(self.plan) if index in seed.waits]

    def edges(self) -> list[tuple[int, int]]:
        return [(source, waiter) for waiter, seed in enumerate(self.plan) for source in seed.waits]

    def all_bloomed(self) -> bool:
        return all(plant.stage == "bloomed" for plant in self.plants)

    # -- moving on ---------------------------------------------------------------------------

    def advance(self, dt: float) -> list[tuple[str, int]]:
        """Move on by ``dt`` seconds; returns what happened: ``("ready", seed)``,
        ``("bloom", seed)``, ``("rest", -1)``, ``("let go", -1)``, ``("sow", -1)``."""
        self.t += dt
        events: list[tuple[str, int]] = []
        if self.season == "growing":
            self._grow(events)
        elif self.season == "resting":
            if self.t - self.since >= REST_S:
                self.season, self.since = "letting go", self.t
                events.append(("let go", -1))
        else:
            wilt = span(self.t, self.since, LET_GO_S)
            for plant in self.plants:
                plant.wilt = wilt
            if wilt >= 1.0:
                self._sow()
                events.append(("sow", -1))
        for agent in self.agents:
            self._move(agent)
        return events

    def _grow(self, events: list[tuple[str, int]]) -> None:
        if self.t - self.since >= FIRST_SPROUT_S:
            for index, plant in enumerate(self.plants):
                if plant.stage == "seed" and not plant.seed.waits:
                    self._sprout(index, events)
        for pulse in [pulse for pulse in self.pulses if pulse.at(self.t) >= 1.0]:
            self.pulses.remove(pulse)
            plant = self.plants[pulse.waiter]
            arriving = any(other.waiter == pulse.waiter for other in self.pulses)
            if plant.stage == "seed" and not arriving and self._fed(pulse.waiter):
                self._sprout(pulse.waiter, events)
        for agent in self.agents:
            if agent.state == "idle":
                self._claim(agent)
            elif agent.state == "flying" and span(self.t, agent.since, agent.flight_s) >= 1.0:
                agent.state, agent.since = "working", self.t
                target = self._target(agent)
                target.stage, target.since = "growing", self.t
            elif agent.state == "working":
                target = self._target(agent)
                target.growth = span(self.t, agent.since, WORK_S)
                if target.growth >= 1.0:
                    self._bloom(agent, events)
        if self.all_bloomed() and not self.pulses:
            self.season, self.since = "resting", self.t
            events.append(("rest", -1))

    def _fed(self, index: int) -> bool:
        return all(self.plants[source].stage == "bloomed" for source in self.plan[index].waits)

    def _sprout(self, index: int, events: list[tuple[str, int]]) -> None:
        plant = self.plants[index]
        plant.stage, plant.since = "ready", self.t
        events.append(("ready", index))

    def _claim(self, agent: Agent) -> None:
        """Take the ready seed nearest, that no other agent has taken."""
        taken = {other.target for other in self.agents if other is not agent}
        ready = [
            index
            for index, plant in enumerate(self.plants)
            if plant.stage == "ready" and index not in taken
        ]
        if not ready:
            return
        index = min(ready, key=lambda seed: (abs(self.plan[seed].x - agent.x), seed))
        start = (agent.x, agent.y)
        end = (self.plan[index].x, HOVER_Y - (0.05 if self.plan[index].milestone else 0.0))
        distance = abs(end[0] - start[0])
        # An arc up and over, higher the further it goes.
        lift = min(start[1], end[1]) - 0.08 - 0.25 * distance
        agent.flight = (
            start,
            (start[0] + (end[0] - start[0]) * 0.25, lift),
            (start[0] + (end[0] - start[0]) * 0.75, lift),
            end,
        )
        agent.flight_s = 0.9 + 1.6 * distance
        agent.state, agent.target, agent.since = "flying", index, self.t
        agent.heading = 1.0 if end[0] >= start[0] else -1.0

    def _bloom(self, agent: Agent, events: list[tuple[str, int]]) -> None:
        index = agent.target
        assert index is not None
        plant = self.plants[index]
        plant.stage, plant.since, plant.growth = "bloomed", self.t, 1.0
        events.append(("bloom", index))
        for waiter in self.waiters(index):
            self.pulses.append(Pulse(index, waiter, self.t))
        agent.state, agent.target, agent.since = "idle", None, self.t
        agent.perch = (agent.x, agent.y)

    def _target(self, agent: Agent) -> Plant:
        assert agent.target is not None
        return self.plants[agent.target]

    def _move(self, agent: Agent) -> None:
        t = self.t
        if agent.state == "flying":
            p = in_out_cubic(span(t, agent.since, agent.flight_s))
            agent.x, agent.y = cubic(*agent.flight, p)
        elif agent.state == "working":
            end = agent.flight[3]
            agent.x = end[0] + 0.004 * math.sin(t * 2.3 + agent.phase)
            agent.y = end[1] + 0.025 * math.sin(t * 3.1 + agent.phase)
        else:
            # Idling: a slow figure of eight about where it came to rest.
            agent.x = agent.perch[0] + 0.008 * math.sin(t * 0.7 + agent.phase)
            agent.y = agent.perch[1] + 0.035 * math.sin(t * 1.4 + agent.phase)

    def _sow(self) -> None:
        self.round += 1
        self.plants = [Plant(seed, since=self.t) for seed in self.plan]
        self.pulses.clear()
        for agent in self.agents:
            agent.state, agent.target, agent.since = "idle", None, self.t
        self.season, self.since = "growing", self.t
