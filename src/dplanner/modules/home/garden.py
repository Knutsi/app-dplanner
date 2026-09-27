"""The garden at Home's foot, as plain state: what DPlanner does, told without a word.

A row of seedlings is the plan; a cloud wearing the agent's glyph drifts over them and
rains; what it rains on grows, and a flower that has had enough rain blooms. When every
flower is in bloom the garden rests a while, goes back to seed, and the season starts again.

Plain data and arithmetic so the rules can be tested without a window: positions are
fractions of the garden's width, time is seconds, and ``page.py``'s ``GardenView`` is the
only thing that knows about pixels, colours or a clock. Qt-free for that reason, not because
the command line reads it.
"""

import math
from dataclasses import dataclass, field

# Where the flowers stand, as fractions of the width — uneven, so the row reads as planted.
PLACES = (0.07, 0.16, 0.27, 0.36, 0.47, 0.57, 0.66, 0.76, 0.86)
# How far each has grown when a season starts: some sprouted, some not yet.
SEEDS = (0.1, 0.35, 0.0, 0.2, 0.45, 0.05, 0.3, 0.15, 0.4)
# The cloud drifts between these, clear of the corner the garden's close button sits in.
CLOUD_LEFT, CLOUD_RIGHT = 0.06, 0.84
DRIFT_S = 36.0  # One crossing and back: slow enough to watch, never to wait on.
GROW_S = 3.0  # Seconds of rain that take a seedling to a bloom.
REST_S = 12.0  # How long a garden in full bloom stays so.
WILT_S = 4.0  # How long going back to seed takes — never a jump.
REACH = 0.05  # Half the rain's width, as a fraction of the garden's.


@dataclass
class Garden:
    growth: list[float] = field(default_factory=lambda: list(SEEDS))
    t: float = 0.0
    # "growing" under the rain, "resting" in full bloom, "wilting" back to seed.
    season: str = "growing"
    rested: float = 0.0

    def cloud_x(self) -> float:
        """Where the cloud is: a slow sweep across and back, easing at either end."""
        swing = 0.5 - 0.5 * math.cos(2 * math.pi * self.t / DRIFT_S)
        return CLOUD_LEFT + (CLOUD_RIGHT - CLOUD_LEFT) * swing

    def rained_on(self, index: int, reach: float = REACH) -> bool:
        return abs(PLACES[index] - self.cloud_x()) <= reach

    def advance(self, dt: float, reach: float = REACH) -> None:
        """Move the garden on by ``dt`` seconds. ``reach`` is the rain's half-width as the
        painter draws it, so a flower grows exactly when rain is seen falling on it."""
        self.t += dt
        if self.season == "growing":
            for index, grown in enumerate(self.growth):
                if self.rained_on(index, reach):
                    self.growth[index] = min(1.0, grown + dt / GROW_S)
            if all(grown >= 1.0 for grown in self.growth):
                self.season, self.rested = "resting", 0.0
        elif self.season == "resting":
            self.rested += dt
            if self.rested >= REST_S:
                self.season = "wilting"
        else:
            self.growth = [
                max(seed, grown - dt / WILT_S)
                for seed, grown in zip(SEEDS, self.growth, strict=True)
            ]
            if all(grown <= seed for seed, grown in zip(SEEDS, self.growth, strict=True)):
                self.season = "growing"
