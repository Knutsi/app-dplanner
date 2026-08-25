"""The application's themes: declarative colour data, nothing else.

A :class:`Theme` carries every theme-dependent colour. ``is_dark`` drives Qt's colour
scheme (native title bars, dialogs); everything else flows through the palette and the
stylesheet template.
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

# -- Omarchy themes -----------------------------------------------------------------------
#
# Recreations of the stock themes of Omarchy Linux (basecamp/omarchy). Each theme's
# background, foreground, accent, selection pair and link colours are the upstream values
# from its colors.toml; the surface/border/text ramps our Theme needs beyond a terminal
# palette are derived with the same proportions the hand-tuned themes above use.


def _mix(a: str, b: str, t: float) -> str:
    """Linear blend of two ``#rrggbb`` colours; ``t`` is the share of ``b``."""
    av, bv = int(a[1:], 16), int(b[1:], 16)
    channels = (
        round(((av >> shift) & 0xFF) * (1 - t) + ((bv >> shift) & 0xFF) * t) for shift in (16, 8, 0)
    )
    return "#{:02x}{:02x}{:02x}".format(*channels)


def _omarchy(
    name: str,
    *,
    bg: str,
    fg: str,
    accent: str,
    selection_bg: str,
    selection_fg: str,
    link: str,
    link_visited: str,
    light: bool = False,
) -> Theme:
    if light:
        return Theme(
            name=name,
            is_dark=False,
            bg_base=bg,
            bg_surface=_mix(bg, "#ffffff", 0.5),
            bg_elevated=_mix(bg, "#000000", 0.05),
            bg_overlay=_mix(bg, "#ffffff", 0.75),
            border=_mix(bg, fg, 0.14),
            border_strong=_mix(bg, fg, 0.24),
            text_primary=fg,
            text_secondary=_mix(fg, bg, 0.28),
            text_disabled=_mix(fg, bg, 0.6),
            accent=accent,
            accent_hover=_mix(accent, "#000000", 0.15),  # Hover darkens on light themes.
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
        bg_surface=_mix(bg, "#000000", 0.25),
        bg_elevated=_mix(bg, "#ffffff", 0.04),
        bg_overlay=_mix(bg, "#ffffff", 0.08),
        border=_mix(bg, fg, 0.12),
        border_strong=_mix(bg, fg, 0.2),
        text_primary=fg,
        text_secondary=_mix(fg, bg, 0.3),
        text_disabled=_mix(fg, bg, 0.62),
        accent=accent,
        accent_hover=_mix(accent, "#ffffff", 0.15),
        on_accent=bg,
        selection_bg=selection_bg,
        selection_fg=selection_fg,
        link=link,
        link_visited=link_visited,
    )


OMARCHY_THEMES: tuple[Theme, ...] = (
    _omarchy(
        "catppuccin",
        bg="#1e1e2e",
        fg="#cdd6f4",
        accent="#89b4fa",
        selection_bg="#f5e0dc",
        selection_fg="#1e1e2e",
        link="#89b4fa",
        link_visited="#f5c2e7",
    ),
    _omarchy(
        "catppuccin-latte",
        light=True,
        bg="#eff1f5",
        fg="#4c4f69",
        accent="#1e66f5",
        selection_bg="#dc8a78",
        selection_fg="#eff1f5",
        link="#1e66f5",
        link_visited="#ea76cb",
    ),
    _omarchy(
        "ethereal",
        bg="#060b1e",
        fg="#ffcead",
        accent="#7d82d9",
        selection_bg="#ffcead",
        selection_fg="#060b1e",
        link="#7d82d9",
        link_visited="#c89dc1",
    ),
    _omarchy(
        "everforest",
        bg="#2d353b",
        fg="#d3c6aa",
        accent="#7fbbb3",
        selection_bg="#d3c6aa",
        selection_fg="#2d353b",
        link="#7fbbb3",
        link_visited="#d699b6",
    ),
    _omarchy(
        "flexoki-light",
        light=True,
        bg="#fffcf0",
        fg="#100f0f",
        accent="#205ea6",
        selection_bg="#cecdc3",
        selection_fg="#100f0f",
        link="#205ea6",
        link_visited="#ce5d97",
    ),
    _omarchy(
        "gruvbox",
        bg="#282828",
        fg="#d4be98",
        accent="#7daea3",
        selection_bg="#d65d0e",
        selection_fg="#ebdbb2",
        link="#7daea3",
        link_visited="#d3869b",
    ),
    _omarchy(
        "hackerman",
        bg="#0b0c16",
        fg="#ddf7ff",
        accent="#82fb9c",
        selection_bg="#ddf7ff",
        selection_fg="#0b0c16",
        link="#829dd4",
        link_visited="#86a7df",
    ),
    _omarchy(
        "kanagawa",
        bg="#1f1f28",
        fg="#dcd7ba",
        accent="#7e9cd8",
        selection_bg="#2d4f67",
        selection_fg="#c8c093",
        link="#7e9cd8",
        link_visited="#957fb8",
    ),
    _omarchy(
        "lumon",
        bg="#16242d",
        fg="#d6e2ee",
        accent="#8bc9eb",
        selection_bg="#4d9ed3",
        selection_fg="#1b2d40",
        link="#6fb8e3",
        link_visited="#8bc9eb",
    ),
    _omarchy(
        "matte-black",
        bg="#121212",
        fg="#bebebe",
        accent="#e68e0d",
        selection_bg="#515151",
        selection_fg="#bebebe",
        link="#e68e0d",
        link_visited="#d35f5f",
    ),
    _omarchy(
        "miasma",
        bg="#222222",
        fg="#c2c2b0",
        accent="#78824b",
        selection_bg="#78824b",
        selection_fg="#c2c2b0",
        link="#78824b",
        link_visited="#bb7744",
    ),
    _omarchy(
        "nord",
        bg="#2e3440",
        fg="#d8dee9",
        accent="#81a1c1",
        selection_bg="#4c566a",
        selection_fg="#d8dee9",
        link="#81a1c1",
        link_visited="#b48ead",
    ),
    _omarchy(
        "osaka-jade",
        bg="#111c18",
        fg="#c1c497",
        accent="#509475",
        selection_bg="#c1c497",
        selection_fg="#111c18",
        link="#509475",
        link_visited="#d2689c",
    ),
    _omarchy(
        "retro-82",
        bg="#05182e",
        fg="#f6dcac",
        accent="#faa968",
        selection_bg="#faa968",
        selection_fg="#00172e",
        link="#faa968",
        link_visited="#3f8f8a",
    ),
    _omarchy(
        "ristretto",
        bg="#2c2525",
        fg="#e6d9db",
        accent="#f38d70",
        selection_bg="#403e41",
        selection_fg="#e6d9db",
        link="#f38d70",
        link_visited="#a8a9eb",
    ),
    _omarchy(
        "rose-pine",  # Master ships the light "dawn" variant.
        light=True,
        bg="#faf4ed",
        fg="#575279",
        accent="#56949f",
        selection_bg="#dfdad9",
        selection_fg="#575279",
        link="#56949f",
        link_visited="#907aa9",
    ),
    _omarchy(
        "tokyo-night",
        bg="#1a1b26",
        fg="#a9b1d6",
        accent="#7aa2f7",
        selection_bg="#7aa2f7",
        selection_fg="#c0caf5",
        link="#7aa2f7",
        link_visited="#ad8ee6",
    ),
    _omarchy(
        "vantablack",
        bg="#000000",
        fg="#ffffff",
        accent="#8d8d8d",
        selection_bg="#ffffff",
        selection_fg="#000000",
        link="#8d8d8d",
        link_visited="#9b9b9b",
    ),
    _omarchy(
        "white",
        light=True,
        bg="#ffffff",
        fg="#000000",
        accent="#6e6e6e",
        selection_bg="#1a1a1a",
        selection_fg="#ffffff",
        link="#1a1a1a",
        link_visited="#2e2e2e",
    ),
)

THEMES: dict[str, Theme] = {theme.name: theme for theme in (DARK, LIGHT, SEPIA, *OMARCHY_THEMES)}
DEFAULT = DARK
