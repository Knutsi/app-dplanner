"""Seeded luck, so a scenario plays the same way every time it is opened — and the same way
the HTML prototype plays it: these are its functions to the bit, 32-bit arithmetic included,
so a seed names one plan and one run in either."""

import math
from collections.abc import Callable, Sequence

Rng = Callable[[], float]  # Uniform in [0, 1).

_MASK = 0xFFFFFFFF


def rng(seed: int) -> Rng:
    """mulberry32: small, fast, and good enough for a simulation nobody bets on."""
    state = seed & _MASK

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _MASK
        t = ((state ^ (state >> 15)) * (state | 1)) & _MASK
        t ^= (t + ((t ^ (t >> 7)) * (t | 61))) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    return draw


def seed_of(seed: int, name: str) -> int:
    """A seed from a seed and a name, so one step's luck does not move when another is
    added (FNV-1a over the name's UTF-16 code units, as the prototype reads a string)."""
    hashed = (seed ^ 0x811C9DC5) & _MASK
    data = name.encode("utf-16-le")
    for at in range(0, len(data), 2):
        hashed = ((hashed ^ int.from_bytes(data[at : at + 2], "little")) * 16777619) & _MASK
    return hashed


def normal(random: Rng) -> float:
    """A standard normal draw (Box-Muller)."""
    u = max(random(), 1e-12)
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * random())


def lognormal(random: Rng, sigma: float) -> float:
    """A factor with mean 1: how far one step's real effort lands from its estimate."""
    return math.exp(sigma * normal(random) - (sigma * sigma) / 2) if sigma else 1.0


def choose[T](random: Rng, items: Sequence[T]) -> T:
    return items[math.floor(random() * len(items))]
