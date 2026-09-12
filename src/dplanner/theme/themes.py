"""The :class:`Theme` record and the house themes.

A :class:`Theme` carries every theme-dependent colour. ``is_dark`` drives Qt's colour
scheme (native title bars, dialogs); everything else flows through the palette and the
stylesheet template. The three themes here are hand-tuned; every other theme the
application offers comes from a provider (:mod:`dplanner.theme.providers`) — the built-in
one adds Omarchy's stock themes, mapped from their ``colors.toml`` by
:mod:`dplanner.theme.omarchy`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    is_dark: bool

    # Surfaces, from furthest back to closest to the reader.
    bg_base: str  # the window itself — also the prose background
    bg_surface: str  # input wells (search field, inspector, notes panel)
    bg_elevated: str  # menubar, statusbar, binder
    bg_overlay: str  # menus, tooltips, popups

    # Hairlines and frames.
    border: str
    border_strong: str

    # Type.
    text_primary: str
    text_secondary: str
    text_disabled: str

    # A warm gold accent so the app reads as "manuscript" rather than "IDE".
    accent: str
    accent_hover: str
    on_accent: str

    # Text selection stays blue in every theme: gold behind body text is unreadable.
    selection_bg: str
    selection_fg: str

    link: str
    link_visited: str


DARK = Theme(
    name="dark",
    is_dark=True,
    bg_base="#14161a",
    bg_surface="#0f1115",
    bg_elevated="#1b1e24",
    bg_overlay="#23272f",
    border="#2b303a",
    border_strong="#39404d",
    text_primary="#e6e8ec",
    text_secondary="#a8b0bd",
    text_disabled="#5c6472",
    accent="#c8a45c",
    accent_hover="#d9b672",
    on_accent="#14161a",
    selection_bg="#33507a",
    selection_fg="#f2f4f7",
    link="#7aa2d6",
    link_visited="#9a86c4",
)

LIGHT = Theme(
    name="light",
    is_dark=False,
    bg_base="#f5f4f1",
    bg_surface="#fcfbf9",
    bg_elevated="#e9e7e2",
    bg_overlay="#ffffff",
    border="#d7d4cd",
    border_strong="#bfbbb1",
    text_primary="#23262b",
    text_secondary="#5d6169",
    text_disabled="#a4a49e",
    accent="#a07c33",
    accent_hover="#8a6a2b",  # Hover darkens on light themes, unlike dark's lighter-on-hover.
    on_accent="#ffffff",
    selection_bg="#b3cdee",
    selection_fg="#10233b",
    link="#2e5e9e",
    link_visited="#6c589e",
)

SEPIA = Theme(
    name="sepia",
    is_dark=False,
    bg_base="#f4ecd9",
    bg_surface="#faf3e3",
    bg_elevated="#eadfc6",
    bg_overlay="#fdf8ec",
    border="#d8cbab",
    border_strong="#c1b28d",
    text_primary="#3b3225",
    text_secondary="#77684e",
    text_disabled="#ab9d80",
    accent="#96712c",
    accent_hover="#7f5f24",
    on_accent="#faf3e3",
    selection_bg="#bccadd",  # Desaturated toward the paper; still clearly a selection.
    selection_fg="#1f2836",
    link="#49688f",
    link_visited="#77639a",
)

DEFAULT = DARK
