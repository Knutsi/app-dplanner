"""How good the Time tab's forecasts are, scenario by scenario — the HTML prototype's
``deno task accuracy`` table, for the model the tab runs.

    uv run python scripts/time_accuracy.py                every scenario
    uv run python scripts/time_accuracy.py by-the-book    one or more, by id

Each scenario is played by the simulator (``time_estimates/simulation/``) over a handful of
seeds, every day written into a library through the real aspect writers and dated by the
real model, and each day's forecast held to when the work really landed: the mean distance
from the truth, how far the forecast travelled in total, and on how many days it moved — all
in working days (``simulation/accuracy.py``). *By the book* must read 0.0 0 0 throughout.
"""

import sys
from dataclasses import replace

from dplanner.modules import _time_readers, _time_writers
from dplanner.modules.time_estimates.simulation.accuracy import (
    Accuracy,
    combined,
    timeline_accuracy,
)
from dplanner.modules.time_estimates.simulation.replay import Replay
from dplanner.modules.time_estimates.simulation.sample import SAMPLE_START, sample_plan
from dplanner.modules.time_estimates.simulation.scenarios import SCENARIOS, scenario_by_id
from dplanner.modules.time_estimates.simulation.world import run

SEEDS = (1, 2, 3, 7, 11, 42)


def cell(found: Accuracy) -> str:
    return f"{found.error:5.1f} {found.movement:4d} {found.moves:4d}"


def main(picked: list[str]) -> int:
    scenarios = [scenario_by_id(one) for one in picked] if picked else list(SCENARIOS)
    readers, writers = _time_readers(), _time_writers()
    print("the landing forecast: mean |error|, total movement, days moved (working days)")
    print(f"seeds {', '.join(map(str, SEEDS))}\n")
    print(f"{'scenario':16}| whole plan       | milestones")
    for scenario in scenarios:
        measured = [
            timeline_accuracy(
                run(sample_plan(seed), replace(scenario.world, seed=seed), SAMPLE_START),
                Replay(scenario.name, writers, readers),
            )
            for seed in SEEDS
        ]
        whole = combined([one.whole for one in measured])
        milestones = combined([one.milestones for one in measured])
        print(f"{scenario.id:16}| {cell(whole)} | {cell(milestones)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
