"""The desktop's own dark or light as a theme provider — macOS, Windows, GNOME and KDE.

Qt reads the platform's colour scheme (``QStyleHints.colorScheme``) on every desktop that
reports one — macOS and Windows always, Linux through the portal or the GTK settings —
and the accent colour on macOS and Windows. The provider is handed those readings as
functions so it stays Qt-free and a test can hand it a desktop; the composition root
wires the real ones. ``current()`` is the built-in dark or light theme wearing the
desktop's accent where there is one; it lists no themes of its own.

The reading is only true while the application holds no colour-scheme override of its
own — ``apply_theme`` sets one for a fixed theme and clears it while following — which is
why availability reads ``scheme_at_start``: the platform's answer before any theme was
applied, which the root memoises.
"""

from collections.abc import Callable
from dataclasses import replace

from dplanner.theme.omarchy import mix
from dplanner.theme.providers import ThemeProvider
from dplanner.theme.themes import DARK, LIGHT, Theme

PROVIDER_ID = "system"

# One row per platform Qt reads a colour scheme on: the label Settings ▸ Appearance shows.
DESKTOPS: dict[str, str] = {
    "darwin": "macOS",
    "win32": "Windows",
    "linux": "Linux desktop (GNOME, KDE)",
}


def _lightness(color: str) -> float:
    value = int(color[1:], 16)
    r, g, b = ((value >> shift) & 0xFF for shift in (16, 8, 0))
    return 0.299 * r + 0.587 * g + 0.114 * b


def with_accent(base: Theme, accent: str) -> Theme:
    """``base`` wearing the desktop's accent: hover shifts the way the base's does, and the
    text on it is white or the base's ink by the accent's own brightness — an OS accent is
    any hue, where a theme's accent was tuned for its ink."""
    hover = mix(accent, "#ffffff" if base.is_dark else "#000000", 0.15)
    on_accent = "#ffffff" if _lightness(accent) < 150 else base.on_accent
    return replace(base, accent=accent, accent_hover=hover, on_accent=on_accent)


def system_provider(
    platform: str,
    *,
    scheme_at_start: Callable[[], str],
    scheme: Callable[[], str],
    accent: Callable[[], str | None],
) -> ThemeProvider:
    """The provider for ``platform`` (``sys.platform``), over the desktop's readings:
    ``scheme``/``scheme_at_start`` answer ``"dark"``, ``"light"`` or ``"unknown"``; ``accent``
    a ``#rrggbb`` or None."""
    desktop = DESKTOPS.get(platform)

    def refusal() -> str | None:
        if desktop is None:
            return f"Not supported on {platform}"
        if scheme_at_start() == "unknown":
            return "This desktop does not report a colour scheme"
        return None

    def current() -> Theme | None:
        base = LIGHT if scheme() == "light" else DARK
        color = accent()
        return base if color is None else with_accent(base, color)

    return ThemeProvider(
        id=PROVIDER_ID, label=desktop or "Desktop", refusal=refusal, current=current
    )
