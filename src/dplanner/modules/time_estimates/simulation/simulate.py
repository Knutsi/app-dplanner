"""One simulation as Debug ▸ Time Simulation shows it: a scenario played on a seed's plan,
re-budgeted and waited on where somebody asked, and recorded as the window would have
recorded it.

Qt-free and the only recipe: the tab asks for a :class:`Setup` and shows the days of what
comes back, so what it shows is also what a test or a script can compute without a window.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.schedule import milestone_colors
from dplanner.modules.time_estimates.simulation.edits import (
    BudgetEdit,
    WaitEdit,
    world_budgets,
    world_waits,
)
from dplanner.modules.time_estimates.simulation.frames import Writers
from dplanner.modules.time_estimates.simulation.replay import Recorded, Replay, record
from dplanner.modules.time_estimates.simulation.sample import SAMPLE_START
from dplanner.modules.time_estimates.simulation.scenarios import (
    SAVED_BY_DEFAULT,
    SCENARIOS,
    scenario_by_id,
)
from dplanner.modules.time_estimates.simulation.timeline import Cadence, Timeline


@dataclass(frozen=True)
class Setup:
    scenario: str = SCENARIOS[0].id
    seed: int = 1
    cadence: Cadence | None = None  # None is the scenario's own.
    budgets: tuple[BudgetEdit, ...] = ()
    waits: tuple[WaitEdit, ...] = ()


@dataclass(frozen=True)
class Simulated:
    setup: Setup
    timeline: Timeline
    recorded: Recorded
    # Each milestone's colour as the plan's last day deals it — for marks that must match
    # the tab's own shades.
    colors: Mapping[str, str]


def simulate(setup: Setup, writers: Writers, readers: Readers) -> Simulated:
    scenario = scenario_by_id(setup.scenario)
    world = replace(
        scenario.world,
        seed=setup.seed,
        budgets=(*scenario.world.budgets, *world_budgets(setup.budgets, SAMPLE_START)),
        waits=(*scenario.world.waits, *world_waits(setup.waits, SAMPLE_START)),
    )
    timeline = scenario.play(setup.seed, world)
    replay = Replay(scenario.name, writers, readers)
    recorded = record(
        timeline,
        replay,
        cadence=setup.cadence or scenario.cadence,
        seed=setup.seed,
        saved=SAVED_BY_DEFAULT,
    )
    colors = milestone_colors(replay.library, replay.project, readers.is_milestone)
    return Simulated(setup, timeline, recorded, colors)
