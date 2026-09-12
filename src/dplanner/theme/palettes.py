"""The colour maps a project's milestones are shaded from.

A milestone's colour is its **place in the sequence**, read off one perceptually ordered
map from data visualisation (viridis, mako, rocket, …) rather than dealt from eight
competing hues: a roadmap is a sequence and should look like one. :func:`shades` deals a
project's milestones evenly along the map it chose — two sit a quarter and three quarters
of the way in, eight fill it — so the order of the shades is the order of the roadmap.

Each map here is the **legible interior** of a published one: the darkest and lightest ends
are left off, because a fill that vanishes into a light theme or a dark one is no colour at
all. That is also why the maps are constants rather than :class:`~dplanner.theme.themes.Theme`
fields — a milestone's shade says *which milestone*, and it has to keep saying it when the
theme changes underneath (DESIGN.md's exception #2, the rule the status tones keep).

**Qt-free, and hex strings throughout.** This file is where the maps live rather than
``modules/time_estimates/`` because three consumers need them and modules never import each
other: the Time tab deals them, the appearance module lists them in *View ▸ Milestone
Colours*, and the canvas, the tables and the report wear the answer. ``theme/`` is the leaf
every module and the framework may import, and a module's Qt-free half may import it too —
which the CLI's ``schedule palette`` and the report's builder both rely on. Turning a hex
into paint is the view's job, always at paint time: a ``QColor`` kept here would go stale
the way ``option.palette`` does (ARCHITECTURE.md's *The palette a painter is handed is a
snapshot*).

*Which* map a project uses, and a milestone's own chosen colour over the dealt one, are the
project's stored assumptions — ``modules/time_estimates/schedule.py`` owns those, and
``FORMAT.md`` has their shape.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """One colour map, as the stops the milestones are shaded between.

    ``stops`` run dark to light, so the first milestone wears the deepest shade.
    """

    id: str
    name: str
    stops: tuple[str, ...]


PALETTES: tuple[Palette, ...] = (
    Palette(
        "viridis",
        "Viridis",
        ("#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58"),
    ),
    Palette(
        "mako",
        "Mako",
        ("#2f1c4f", "#3b3f7c", "#3b5f92", "#3c7da0", "#47a1ad", "#6dc1ae"),
    ),
    Palette(
        "crest",
        "Crest",
        ("#2a4e7d", "#2d5f8c", "#37739c", "#3f87a3", "#4b9ba2", "#5fae9d", "#7fbf98"),
    ),
    Palette(
        "plasma",
        "Plasma",
        ("#46039f", "#7201a8", "#9c179e", "#bd3786", "#d8576b", "#ed7953", "#fb9f3a"),
    ),
    Palette(
        "magma",
        "Magma",
        ("#3b0f70", "#641a80", "#8c2981", "#b73779", "#de4968", "#f7705c", "#fe9f6d"),
    ),
    Palette(
        "inferno",
        "Inferno",
        ("#420a68", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06"),
    ),
    Palette(
        "rocket",
        "Rocket",
        ("#2c1439", "#5b1a4c", "#8a1f55", "#b7284e", "#dc4b3b", "#f07a3a", "#f8a952"),
    ),
    Palette(
        "flare",
        "Flare",
        ("#5d3444", "#77384f", "#913c56", "#a94057", "#be4a54", "#cf5b4f", "#da6f52", "#e79a6d"),
    ),
    Palette(
        "cividis",
        "Cividis",
        ("#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a59c74", "#c3b369"),
    ),
)
DEFAULT_PALETTE = PALETTES[0].id


def palette(palette_id: str | None) -> Palette:
    """The palette by id; anything unknown — or None — reads as the default."""
    return next((found for found in PALETTES if found.id == palette_id), PALETTES[0])


def _mix(low: str, high: str, share: float) -> str:
    """The colour ``share`` of the way from ``low`` to ``high``, channel by channel."""

    def channel(offset: int) -> int:
        start, end = int(low[offset : offset + 2], 16), int(high[offset : offset + 2], 16)
        return round(start + (end - start) * share)

    return "#" + "".join(f"{channel(offset):02x}" for offset in (1, 3, 5))


def shade(found: Palette, position: float) -> str:
    """The colour ``position`` of the way along the map, 0 to 1, blended between stops."""
    stops = found.stops
    place = min(max(position, 0.0), 1.0) * (len(stops) - 1)
    index = min(int(place), len(stops) - 2)
    return _mix(stops[index], stops[index + 1], place - index)


def shades(found: Palette, count: int) -> list[str]:
    """``count`` shades dealt evenly along the map, centred — one milestone sits in the
    middle, two at a quarter and three quarters, so no shade ever lands on an end."""
    return [shade(found, (index + 0.5) / count) for index in range(count)]
