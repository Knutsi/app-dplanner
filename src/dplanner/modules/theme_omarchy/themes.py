"""Omarchy's desktop theme as a theme provider.

Omarchy 4 stages the current theme under ``~/.local/state/omarchy/current/theme/`` — a
directory ``omarchy-theme-set`` removes and replaces, then names in ``theme.name`` beside
it — and keeps the themes a person made or overlaid under ``~/.config/omarchy/themes``.
This provider reads both: ``current()`` is the staged ``colors.toml`` mapped by
:func:`dplanner.theme.omarchy.theme_from_colors`, and the person's own themes are offered
beside the built-in defaults, which are Omarchy's stock themes generated from the same
kind of file. A read that lands while the directory is being replaced answers None, and
the service keeps what it has until the next poll.

The paths are parameters so a test hands over a tree of its own; the defaults follow XDG.
"""

import os
from pathlib import Path

from dplanner.theme.omarchy import read_colors, theme_from_colors
from dplanner.theme.providers import ThemeGroup, ThemeProvider
from dplanner.theme.themes import Theme

PROVIDER_ID = "omarchy"
OWN_THEMES = "Your Omarchy themes"


def default_state_dir() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state_home) / "omarchy" / "current"


def default_themes_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "omarchy" / "themes"


def omarchy_provider(
    state_dir: Path | None = None, themes_dir: Path | None = None
) -> ThemeProvider:
    state = state_dir if state_dir is not None else default_state_dir()
    own = themes_dir if themes_dir is not None else default_themes_dir()
    colors_file = state / "theme" / "colors.toml"

    def refusal() -> str | None:
        if colors_file.is_file():
            return None
        return f"Omarchy 4 or later is not installed on this machine (no {colors_file})"

    def groups() -> tuple[ThemeGroup, ...]:
        themes: list[Theme] = []
        if own.is_dir():
            # A directory without a readable colors.toml — an empty one, a clone of an
            # older theme — is not a theme; it is skipped rather than listed unusable.
            for directory in sorted(own.iterdir()):
                colors = read_colors(directory / "colors.toml")
                if colors is None:
                    continue
                try:
                    themes.append(theme_from_colors(directory.name, colors))
                except ValueError:
                    continue
        return (ThemeGroup(OWN_THEMES, tuple(themes)),) if themes else ()

    def current() -> Theme | None:
        colors = read_colors(colors_file)
        if colors is None:
            return None
        try:
            name = (state / "theme.name").read_text(encoding="utf-8").strip()
        except OSError:
            name = ""
        try:
            return theme_from_colors(name or PROVIDER_ID, colors)
        except ValueError:
            return None

    return ThemeProvider(
        id=PROVIDER_ID, label="Omarchy", refusal=refusal, groups=groups, current=current
    )
