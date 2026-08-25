"""Build the application ``QPalette`` from a theme.

The palette carries most of the theme. A stylesheet only affects the widgets and properties
its selectors happen to match; the palette governs everything else — disabled states, text
selection inside ``QTextDocument``, placeholder text, standard dialogs, focus rings, and every
widget for which no rule has been written. Relying on the stylesheet alone is how applications
end up with one stubborn white sub-widget.
"""

from PySide6.QtGui import QColor, QPalette

from dplanner.theme.themes import Theme

# Fusion paints unfocused windows from the Inactive group. Populating only Active is why dark
# themes appear to "go light" the moment the window loses focus.
_ALL_GROUPS = (
    QPalette.ColorGroup.Active,
    QPalette.ColorGroup.Inactive,
    QPalette.ColorGroup.Disabled,
)


def _role(name: str) -> QPalette.ColorRole | None:
    """Resolve a colour role by name, tolerating roles absent in older Qt versions."""
    return getattr(QPalette.ColorRole, name, None)


def build_palette(theme: Theme) -> QPalette:
    """Return the application-wide palette for ``theme``."""
    roles: dict[str, str] = {
        "Window": theme.bg_base,
        "WindowText": theme.text_primary,
        "Base": theme.bg_surface,
        "AlternateBase": theme.bg_elevated,
        "ToolTipBase": theme.bg_overlay,
        "ToolTipText": theme.text_primary,
        "Text": theme.text_primary,
        "PlaceholderText": theme.text_disabled,
        "Button": theme.bg_elevated,
        "ButtonText": theme.text_primary,
        "BrightText": theme.accent_hover,
        "Link": theme.link,
        "LinkVisited": theme.link_visited,
        "Highlight": theme.selection_bg,
        "HighlightedText": theme.selection_fg,
        "Light": theme.border_strong,
        "Midlight": theme.border,
        "Mid": theme.border,
        "Dark": theme.bg_surface,
        "Shadow": "#000000",
        # Accent is Qt 6.6+; resolved defensively below.
        "Accent": theme.accent,
    }
    # Fusion derives disabled colours from the enabled ones, and does so badly on extreme
    # palettes — disabled text comes out nearly indistinguishable. Override explicitly.
    disabled_roles: dict[str, str] = {
        "WindowText": theme.text_disabled,
        "Text": theme.text_disabled,
        "ButtonText": theme.text_disabled,
        "ToolTipText": theme.text_disabled,
        "Highlight": theme.bg_overlay,
        "HighlightedText": theme.text_disabled,
        "Base": theme.bg_base,
        "Button": theme.bg_base,
    }

    palette = QPalette()
    for name, value in roles.items():
        role = _role(name)
        if role is None:
            continue
        color = QColor(value)
        for group in _ALL_GROUPS:
            palette.setColor(group, role, color)
    for name, value in disabled_roles.items():
        role = _role(name)
        if role is None:
            continue
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    return palette
