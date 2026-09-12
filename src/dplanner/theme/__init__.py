"""Application theming.

Single entry point: :func:`apply_theme`. This package imports nothing else from ``dplanner``,
so it can be exercised in isolation. Themes are declared in :mod:`dplanner.theme.themes`
and offered by providers (:mod:`dplanner.theme.providers`); switching at runtime is the
framework's ThemeService calling :func:`apply_theme` again.

Importing the package loads no Qt: the themes, the providers and the Omarchy mapping are
plain data and functions a provider module reads without a graphics stack, so the Qt half
is imported inside :func:`apply_theme`, the one function that needs it.
"""

from importlib import resources
from string import Template
from typing import TYPE_CHECKING

from dplanner.theme import tokens
from dplanner.theme.themes import DEFAULT, Theme

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

__all__ = ["apply_theme", "load_stylesheet", "tokens"]


def load_stylesheet(theme: Theme = DEFAULT) -> str:
    """Read ``theme.qss`` and substitute the design tokens for ``theme`` into it.

    Uses ``Template.substitute`` rather than ``safe_substitute`` deliberately: a mistyped token
    should fail loudly at startup instead of silently leaving a literal ``$FOO`` in the
    stylesheet, where Qt would discard the surrounding rule without complaint.
    """
    raw = resources.files(__package__).joinpath("theme.qss").read_text(encoding="utf-8")
    return Template(raw).substitute(tokens.as_qss_mapping(theme))


def apply_theme(
    app: "QApplication", theme: Theme = DEFAULT, *, follow_system: bool = False
) -> None:
    """Apply ``theme`` to ``app``. Safe to call again to switch themes at runtime.

    ``follow_system`` says the theme is the desktop's own, read from it by a following
    provider: the application then holds no colour-scheme override, so the platform's
    reading stays readable — Qt answers ``colorScheme()`` with an override once one is set,
    which would make a provider hear the application's own echo — and the title bar follows
    the desktop, which agrees with the theme by construction.

    The order of these five steps matters:

    1. ``setStyle`` re-polishes widgets and resets standard palettes, so it must come first.
       Fusion is the palette-driven style, and the reason the result looks identical on macOS
       and Linux — the native macOS style paints from system colours and largely ignores a
       custom palette. It is wrapped in a proxy for the per-platform style hints and the
       themed standard icons in :mod:`dplanner.theme.style`, and it is *rebuilt* for each
       theme because a style caches the icons it is asked for.
    2. ``setColorScheme`` (or clearing it) invalidates Qt's cached system palette, so it must
       precede our own.
       This is the highest-value call here: on macOS it sets ``NSApp.appearance``, which
       flips the window title bar, the traffic-light strip and native dialogs — none of
       which a QPalette can reach.
    3. Explicitly-set palette entries survive later theme changes, unlike derived ones.
    4. Chrome font.
    5. The stylesheet last: narrowest scope, and it wins wherever its selectors match.
    """
    from PySide6.QtCore import Qt

    from dplanner.theme.fonts import ui_font
    from dplanner.theme.palette import build_palette
    from dplanner.theme.style import build_style

    app.setStyle(build_style(theme))

    style_hints = app.styleHints()
    # setColorScheme is Qt 6.8+; without it we lose only the native title-bar switching.
    if follow_system and hasattr(style_hints, "unsetColorScheme"):
        style_hints.unsetColorScheme()
    elif hasattr(style_hints, "setColorScheme"):
        style_hints.setColorScheme(Qt.ColorScheme.Dark if theme.is_dark else Qt.ColorScheme.Light)

    app.setPalette(build_palette(theme))
    app.setFont(ui_font())
    app.setStyleSheet(load_stylesheet(theme))
