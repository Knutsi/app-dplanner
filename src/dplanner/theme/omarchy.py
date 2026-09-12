"""Omarchy's ``colors.toml`` as a :class:`Theme`: the one mapping, read by two providers.

The built-in provider carries every theme Omarchy ships, generated from the files under
``$OMARCHY_PATH/themes`` into :mod:`dplanner.theme.omarchy_themes`; the Omarchy provider
reads the desktop's staged theme and the person's own ones live. Both go through
:func:`theme_from_colors`, so a colour cannot mean one thing when generated and another
when followed.

**Anchors from the file, ramps derived.** A ``colors.toml`` is a terminal palette — a
background, a foreground, an accent, a selection wash and the ANSI hues — and the file's
own shades are not the ramp a window needs: ``solitude`` ships a ``lighter_background``
equal to its ``background``, and ``catppuccin-latte``'s "lighter" background is darker than
its base. So the mapping takes exactly the anchors a person tunes — background, foreground,
accent, the selection pair, blue and magenta for the links, the mode — and derives every
surface, border and secondary text with the proportions the hand-tuned house themes use,
which is what the invariants in ``tests/test_theme.py`` prove for every theme at once. The
ANSI hues reach a :class:`Theme` only as its links: status tints are constant tones by
design (DESIGN.md's exception #2).

Qt-free, like everything in this package but :func:`dplanner.theme.apply_theme`.
"""

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from dplanner.theme.themes import Theme

HEX = re.compile(r"^#[0-9a-f]{6}$")


def mix(a: str, b: str, t: float) -> str:
    """Linear blend of two ``#rrggbb`` colours; ``t`` is the share of ``b``."""
    av, bv = int(a[1:], 16), int(b[1:], 16)
    channels = (
        round(((av >> shift) & 0xFF) * (1 - t) + ((bv >> shift) & 0xFF) * t) for shift in (16, 8, 0)
    )
    return "#{:02x}{:02x}{:02x}".format(*channels)


def read_colors(path: Path) -> dict[str, str] | None:
    """The string values of a ``colors.toml``, lower-cased.

    None when the file cannot be read as one — which is also the window in which
    ``omarchy-theme-set`` has removed the theme directory and not yet moved the next one in,
    so a reader answers "nothing to say" rather than raising.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return {key: value.lower() for key, value in data.items() if isinstance(value, str)}


def is_light(colors: Mapping[str, str]) -> bool:
    """Omarchy's own cascade (``omarchy-theme-color``): ``mode``, the older ``theme_type``,
    then the background's brightness — ``r + g + b > 382`` reads as light. Every stock theme
    carries ``mode``; the rest is for a person's theme that predates it."""
    mode = colors.get("mode") or colors.get("theme_type")
    if mode:
        return mode == "light"
    background = _hex(colors, "background")
    if background is None:
        return False
    value = int(background[1:], 16)
    return sum((value >> shift) & 0xFF for shift in (16, 8, 0)) > 382


def _hex(colors: Mapping[str, str], *keys: str) -> str | None:
    """The first of ``keys`` holding a ``#rrggbb``. A value in another form — Hyprland's
    ``rgba(…)`` strings ride along in a few files — counts as absent."""
    for key in keys:
        value = colors.get(key)
        if value is not None and HEX.match(value):
            return value
    return None


def theme_from_colors(name: str, colors: Mapping[str, str]) -> Theme:
    """A theme named ``name`` from a ``colors.toml``'s values.

    ``ValueError`` when the file names no background or foreground: the two anchors nothing
    can stand in for. Everything else has a fallback in Omarchy's own order — ``accent``
    then ``blue``; ``selection`` then ``muted``; ``bright_foreground`` for the selected
    text, as its terminals do.
    """
    bg = _hex(colors, "background")
    fg = _hex(colors, "foreground")
    if bg is None or fg is None:
        raise ValueError(f"{name}: colors.toml names no background or foreground")
    accent = _hex(colors, "accent", "blue") or fg
    selection_bg = _hex(colors, "selection", "muted") or mix(bg, fg, 0.2)
    selection_fg = _hex(colors, "bright_foreground") or fg
    link = _hex(colors, "blue") or accent
    link_visited = _hex(colors, "magenta") or link
    if is_light(colors):
        return Theme(
            name=name,
            is_dark=False,
            bg_base=bg,
            bg_surface=mix(bg, "#ffffff", 0.5),
            bg_elevated=mix(bg, "#000000", 0.05),
            bg_overlay=mix(bg, "#ffffff", 0.75),
            border=mix(bg, fg, 0.14),
            border_strong=mix(bg, fg, 0.24),
            text_primary=fg,
            text_secondary=mix(fg, bg, 0.28),
            text_disabled=mix(fg, bg, 0.6),
            accent=accent,
            accent_hover=mix(accent, "#000000", 0.15),  # Hover darkens on light themes.
            on_accent="#ffffff",
            selection_bg=selection_bg,
            selection_fg=selection_fg,
            link=link,
            link_visited=link_visited,
        )
    return Theme(
        name=name,
        is_dark=True,
        bg_base=bg,
        bg_surface=mix(bg, "#000000", 0.25),
        bg_elevated=mix(bg, "#ffffff", 0.04),
        bg_overlay=mix(bg, "#ffffff", 0.08),
        border=mix(bg, fg, 0.12),
        border_strong=mix(bg, fg, 0.2),
        text_primary=fg,
        text_secondary=mix(fg, bg, 0.3),
        text_disabled=mix(fg, bg, 0.62),
        accent=accent,
        accent_hover=mix(accent, "#ffffff", 0.15),
        on_accent=bg,
        selection_bg=selection_bg,
        selection_fg=selection_fg,
        link=link,
        link_visited=link_visited,
    )
