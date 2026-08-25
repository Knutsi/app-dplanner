"""Runtime theme switching and persistence.

The theme package stays a pure library (apply a given theme to an application); this
service owns *which* theme is current: it persists the choice in ``QSettings`` and tells
the few views that cache painted colours (icons) to refresh. Everything else
follows automatically — ``apply_theme`` re-sets the palette and stylesheet, which Qt
propagates and re-polishes on its own.
"""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from dplanner.core.signals import Signal
from dplanner.theme import apply_theme
from dplanner.theme.themes import DEFAULT, THEMES, Theme

SETTINGS_KEY = "appearance/theme"


def saved_theme() -> Theme:
    """The persisted theme, falling back to the default for missing or unknown names."""
    name = QSettings().value(SETTINGS_KEY, "")
    return THEMES.get(str(name), DEFAULT)


class ThemeService:
    def __init__(self, app: QApplication, current: Theme | None = None) -> None:
        self._app = app
        self.current = current or saved_theme()
        self.changed: Signal[Theme] = Signal()

    def set_theme(self, name: str) -> None:
        theme = THEMES[name]
        if theme is self.current:
            return
        self.current = theme
        apply_theme(self._app, theme)
        QSettings().setValue(SETTINGS_KEY, theme.name)
        self.changed.emit(theme)
