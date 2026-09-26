"""A synthetic plan shaped like the real ones the Time tab was designed against.

What the real plans have in common: one start step; milestones in a chain, each gathering
what branches out of the previous one and collects into it; most steps agent work sized in
quarter days; a few human steps sized in whole days; milestone steps opted out of
estimating; and a couple of steps nobody has sized yet. The seed changes the shape, never
the kind — and names the same plan the HTML prototype's seed does.
"""

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta

from dplanner.modules.time_estimates.simulation.frames import Plan, PlanState, StepState
from dplanner.modules.time_estimates.simulation.rng import Rng, choose, rng

SAMPLE_START = date(2026, 10, 5)  # A Monday.

VERBS = (
    "Model",
    "Wire",
    "Draw",
    "Store",
    "Import",
    "Export",
    "Validate",
    "Test",
    "Measure",
    "Document",
    "Cache",
    "Index",
)
NOUNS = (
    "the ledger",
    "the parser",
    "the report",
    "the gateway",
    "the settings",
    "the importer",
    "the calendar",
    "the audit log",
    "the search",
    "the sync",
    "the dashboard",
    "the onboarding",
)
HUMAN = (
    "Review the design",
    "Decide the data model",
    "Usability walkthrough",
    "Security review",
    "Write the migration guide",
    "Pair on the hard part",
)
AGENT_DAYS = (0.25, 0.25, 0.5, 0.5, 0.75, 1.0, 1.5)
HUMAN_DAYS = (1.0, 1.0, 2.0, 2.0, 3.0, 5.0)


@dataclass(frozen=True)
class SampleShape:
    milestones: int = 4
    branches: tuple[int, int] = (2, 3)  # Parallel chains per stretch, least and most.
    chain: tuple[int, int] = (2, 4)  # Steps per chain.
    agent_share: float = 0.75
    unestimated: int = 2


SAMPLE_SHAPE = SampleShape()


def _between(random: Rng, span: tuple[int, int]) -> int:
    least, most = span
    return least + math.floor(random() * (most - least + 1))


def sample_plan(seed: int, shape: SampleShape = SAMPLE_SHAPE) -> Plan:
    random = rng(seed)
    made = SAMPLE_START - timedelta(days=7)
    steps: list[StepState] = []

    def add(
        title: str,
        *,
        requires: tuple[str, ...],
        estimate: float | None = None,
        off: bool = False,
        milestone: str = "",
        agent: bool = False,
    ) -> str:
        number = len(steps) + 1
        steps.append(
            StepState(
                id=f"s{number}",
                number=number,
                title=title,
                requires=requires,
                estimate=estimate,
                off=off,
                milestone=milestone,
                agent=agent,
                created=made,
                start=None,
                status="pending",
                since=None,
                started=None,
            )
        )
        return f"s{number}"

    previous = add("Project start", requires=(), estimate=0.0)
    for index in range(1, shape.milestones + 1):
        ends: list[str] = []
        # Both counts are drawn afresh at every turn of their loop, as the prototype's
        # loop conditions draw them: the same seed then deals the same plan.
        branch = 0
        while branch < _between(random, shape.branches):
            at = previous
            link = 0
            while link < _between(random, shape.chain):
                if random() < shape.agent_share:
                    title = f"{choose(random, VERBS)} {choose(random, NOUNS)}"
                    days = choose(random, AGENT_DAYS)
                    at = add(title, requires=(at,), estimate=days, agent=True)
                else:
                    title = choose(random, HUMAN)
                    at = add(title, requires=(at,), estimate=choose(random, HUMAN_DAYS))
                link += 1
            ends.append(at)
            branch += 1
        previous = add(f"Release {index}", requires=tuple(ends), off=True, milestone=f"M{index}")
    sized = [index for index, step in enumerate(steps) if step.estimate and index != 0]
    for _left in range(shape.unestimated):
        if not sized:
            break
        index = sized.pop(math.floor(random() * len(sized)))
        steps[index] = replace(steps[index], estimate=None)
    return Plan(
        title=f"Sample plan (seed {seed})",
        state=PlanState(start=SAMPLE_START, efficiency=0.5, team=(1, 2), efficiency_was=None),
        steps=tuple(steps),
    )
