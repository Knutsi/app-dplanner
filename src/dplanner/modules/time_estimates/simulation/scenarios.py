"""The scenarios: each breaks one assumption the model makes, so whatever the tab does
afterwards can be put down to that one thing. *By the book* breaks none, which makes it the
control: any gap it shows between forecast and reality is the model's own.

The first twelve are the HTML prototype's, with the same worlds, so a scenario and a seed
name one run in either. The last three are milestones worked in parallel, which only this
simulator plays; like *By the book* they size every step, so what they show is theirs alone.
"""

from dataclasses import dataclass, replace

from dplanner.modules.time_estimates.simulation.replay import SavedSpec
from dplanner.modules.time_estimates.simulation.sample import (
    SAMPLE_SHAPE,
    SAMPLE_START,
    SampleShape,
    sample_plan,
)
from dplanner.modules.time_estimates.simulation.timeline import Cadence, Timeline
from dplanner.modules.time_estimates.simulation.world import (
    DEFAULT_WORLD,
    Block,
    BudgetChange,
    WorldParams,
    run,
)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    breaks: str  # The assumption, in the model's words.
    world: WorldParams
    cadence: Cadence = "weekdays"
    shape: SampleShape = SAMPLE_SHAPE  # The plan the team is handed.

    def play(self, seed: int, world: WorldParams | None = None) -> Timeline:
        """The seed's plan in this scenario's shape, played in its world — or in ``world``,
        where somebody changed it — seeded alike."""
        return run(
            sample_plan(seed, self.shape), replace(world or self.world, seed=seed), SAMPLE_START
        )


SAVED_BY_DEFAULT = (
    SavedSpec(0, "Kickoff review", "The plan as it was presented on the first day."),
    SavedSpec(21, "Three-week check-in", "Where we thought we were after three weeks."),
)

SCENARIOS = (
    Scenario(
        "by-the-book",
        "By the book",
        "nothing — every step takes exactly its estimate and nothing happens to the plan",
        replace(DEFAULT_WORLD, unestimated_effort=0.0),
    ),
    Scenario(
        "unsized",
        "Unsized steps",
        "a step nobody estimated costs nothing — each really takes two days",
        replace(DEFAULT_WORLD, unestimated_effort=2.0),
    ),
    Scenario(
        "optimistic",
        "Optimistic estimates",
        "the estimates are right — human work really takes 1.5 times its estimate",
        replace(DEFAULT_WORLD, human_bias=1.5, noise=0.25),
    ),
    Scenario(
        "scope-creep",
        "Scope creep",
        "the plan is complete — about three steps every two weeks are added to the milestone "
        "being worked",
        replace(DEFAULT_WORLD, scope_per_week=1.5),
    ),
    Scenario(
        "learning",
        "Learning re-estimates",
        "the first estimates are final — they are 1.5 times too low, and every week the team "
        "re-estimates the three largest waiting steps",
        replace(DEFAULT_WORLD, human_bias=1.5, reestimate_every=5, reestimate_factor=1.5),
    ),
    Scenario(
        "joiner",
        "Someone joins",
        "the team stays as it is — a second person and a third agent join on day 14",
        replace(DEFAULT_WORLD, budgets=(BudgetChange(after=14, humans=2, agents=3),)),
    ),
    Scenario(
        "blocked",
        "A blocked step",
        "nothing waits — the longest-running step is blocked for six working days on day 8",
        replace(DEFAULT_WORLD, block=Block(after=8, days=6)),
    ),
    Scenario(
        "work-ahead",
        "Team works ahead",
        "milestones run in sequence — idle people start the next milestone's ready work",
        replace(DEFAULT_WORLD, work_ahead=True),
    ),
    Scenario(
        "undated",
        "Undated project",
        "the plan has a start date — nobody set one, so it starts “today”, every day",
        replace(DEFAULT_WORLD, dated=False),
    ),
    Scenario(
        "sparse",
        "Window rarely open",
        "the recorder sees every day — the window is opened on Mondays and Thursdays",
        replace(DEFAULT_WORLD, human_bias=1.3, noise=0.3),
        cadence="twice-weekly",
    ),
    Scenario(
        "supervision",
        "Agents need supervision",
        "agent work costs no human time — each running agent step takes a quarter of a "
        "person's day",
        replace(DEFAULT_WORLD, agent_load=0.25),
    ),
    Scenario(
        "realistic",
        "A realistic mix",
        "several at once — optimistic estimates, noise, some scope creep, occasional re-estimates",
        replace(
            DEFAULT_WORLD,
            human_bias=1.3,
            agent_bias=1.1,
            noise=0.35,
            scope_per_week=1.0,
            reestimate_every=10,
            reestimate_factor=1.25,
        ),
    ),
    Scenario(
        "two-tracks",
        "Two tracks",
        "one milestone's work waits for the last — the plan is two tracks of milestones that "
        "never wait on each other, and idle hands work the second",
        replace(DEFAULT_WORLD, unestimated_effort=0.0, work_ahead=True),
        shape=replace(SAMPLE_SHAPE, tracks=2),
    ),
    Scenario(
        "multitasking",
        "Multitasking",
        "a person works one step at a time — each keeps two going, their focus split between them",
        replace(DEFAULT_WORLD, unestimated_effort=0.0, juggle=2),
    ),
    Scenario(
        "late-marking",
        "Late marking",
        "a step is marked done the day it lands — it is marked the next working morning",
        replace(DEFAULT_WORLD, unestimated_effort=0.0, mark_late=True),
    ),
)


def scenario_by_id(scenario_id: str) -> Scenario:
    return next((found for found in SCENARIOS if found.id == scenario_id), SCENARIOS[0])
