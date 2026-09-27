"""Particles: many small things that are born, drift, fade and are gone.

Plain state, no Qt: a painter draws them (``draw.py``), and a model or a view emits and steps
them. Each carries its own ``tone`` — an index the painter maps to a colour — and ``shape``,
so one system can hold glitter and petals at once and still be drawn in a pass per kind.
A capacity bounds it: a burst that would outgrow it retires the oldest first, so a surface
never pays for more than it can show.
"""

import math
from dataclasses import dataclass, field


@dataclass
class Particle:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    life: float = 1.0  # Seconds it lives.
    age: float = 0.0
    size: float = 2.0
    tone: int = 0
    shape: str = "dot"  # What the painter draws: "dot", "spark", "petal".
    angle: float = 0.0
    spin: float = 0.0  # Radians a second.
    twinkle: float = 0.0  # A phase, so a field of them does not blink in step.

    @property
    def fade(self) -> float:
        """1 when born, 0 when gone: in quickly, out slowly."""
        p = self.age / self.life if self.life > 0 else 1.0
        return min(1.0, p * 8.0) * (1.0 - p) ** 1.5 if p < 1.0 else 0.0


@dataclass
class Particles:
    capacity: int = 400
    items: list[Particle] = field(default_factory=list)

    def emit(self, particle: Particle) -> None:
        if len(self.items) >= self.capacity:
            self.items.pop(0)
        self.items.append(particle)

    def step(
        self,
        dt: float,
        *,
        gravity: float = 0.0,
        drag: float = 0.0,
        wind: float = 0.0,
        floor: float | None = None,
    ) -> None:
        """Age and move every particle; ``floor`` is where a falling one lands and goes."""
        keep = math.exp(-drag * dt) if drag > 0 else 1.0
        alive: list[Particle] = []
        for item in self.items:
            item.age += dt
            if item.age >= item.life:
                continue
            item.vx = (item.vx + wind * dt) * keep
            item.vy = (item.vy + gravity * dt) * keep
            item.x += item.vx * dt
            item.y += item.vy * dt
            item.angle += item.spin * dt
            if floor is not None and item.y >= floor and item.vy > 0:
                continue
            alive.append(item)
        self.items = alive

    def clear(self) -> None:
        self.items.clear()

    def __len__(self) -> int:
        return len(self.items)
