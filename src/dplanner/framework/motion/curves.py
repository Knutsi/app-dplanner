"""Time and space made smooth: easing curves, a tween, a spring, a breeze and a Bézier.

Plain arithmetic, no Qt, so a model that moves (``modules/home/garden.py``) can be tested
without a window and a render can set its clock by hand. Every easing takes a progress in
``[0, 1]`` and returns one — ``out_back`` overshoots on purpose, which is what makes a thing
that grows look as though it arrived rather than stopped.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

type Ease = Callable[[float], float]
type Point = tuple[float, float]


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def lerp(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def span(elapsed: float, start: float, duration: float) -> float:
    """How far through ``[start, start + duration]`` ``elapsed`` is, clamped — the progress
    one part of a staged animation hands its easing."""
    if duration <= 0.0:
        return 1.0 if elapsed >= start else 0.0
    return clamp01((elapsed - start) / duration)


# -- easings: progress in, progress out ---------------------------------------------------------


def linear(p: float) -> float:
    return p


def in_out_sine(p: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * p)


def out_cubic(p: float) -> float:
    return 1.0 - (1.0 - p) ** 3


def in_out_cubic(p: float) -> float:
    return 4.0 * p**3 if p < 0.5 else 1.0 - (-2.0 * p + 2.0) ** 3 / 2.0


def out_quint(p: float) -> float:
    return 1.0 - (1.0 - p) ** 5


def out_back(p: float, overshoot: float = 1.70158) -> float:
    """Past the mark and back: the arrival of something that grows."""
    lift = overshoot + 1.0
    return 1.0 + lift * (p - 1.0) ** 3 + overshoot * (p - 1.0) ** 2


def smoothstep(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


# -- a tween: one value from here to there -------------------------------------------------------


@dataclass(frozen=True)
class Tween:
    """A value going from ``start`` to ``end`` over ``duration`` seconds after ``delay``."""

    start: float
    end: float
    duration: float
    delay: float = 0.0
    ease: Ease = out_cubic

    def at(self, elapsed: float) -> float:
        return lerp(self.start, self.end, self.ease(span(elapsed, self.delay, self.duration)))

    def done(self, elapsed: float) -> bool:
        return elapsed >= self.delay + self.duration


# -- a spring: a value that follows a target -----------------------------------------------------


@dataclass
class Spring:
    """A value pulled towards ``target``: what makes a thing that is moved glide and settle.

    ``stiffness`` is how hard it pulls and ``damping`` how much it resists; the default damping
    is critical — the fastest arrival that never overshoots. Lower it for a bounce. Stepped in
    slices of at most a two-hundred-and-fortieth of a second, so a long frame never shoots it
    past where it should be.
    """

    value: float
    target: float
    velocity: float = 0.0
    stiffness: float = 170.0
    damping: float = 2.0 * math.sqrt(170.0)

    def step(self, dt: float) -> float:
        remaining = dt
        while remaining > 0.0:
            slice_ = min(remaining, 1.0 / 240.0)
            force = self.stiffness * (self.target - self.value) - self.damping * self.velocity
            self.velocity += force * slice_
            self.value += self.velocity * slice_
            remaining -= slice_
        return self.value

    def settled(self, tolerance: float = 1e-3) -> bool:
        return abs(self.target - self.value) < tolerance and abs(self.velocity) < tolerance


# -- a breeze: coherent wobble -------------------------------------------------------------------


def breeze(t: float, x: float) -> float:
    """A gust in ``[-1, 1]`` at time ``t`` and place ``x``: sines at unrelated rates, so
    neighbours sway together and nothing repeats in a way the eye picks up."""
    return (
        0.55 * math.sin(0.9 * t + 0.013 * x)
        + 0.3 * math.sin(1.7 * t - 0.031 * x + 1.3)
        + 0.15 * math.sin(3.1 * t + 0.057 * x + 4.1)
    )


# -- a Bézier: a smooth way from here to there ----------------------------------------------------


def cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )
