"""The "Appearance" settings page: every theme provider, and a switch for each.

Per user, per machine — a GLOBAL-scope preference: which providers this person wants
offered. A provider that does not apply here shows its reason under a box that cannot be
ticked; the built-in one is a line rather than a box, since a switch that cannot be turned
off is a control that teaches nothing (DESIGN.md's *Words*).
"""

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from dplanner.framework.theme_service import ThemeService
from dplanner.theme.providers import BUILTIN, ThemeProvider


def provider_words(provider: ThemeProvider, theme: ThemeService) -> str:
    """The line under a provider: why it is not offered here, else what it can do."""
    reason = theme.refusal(provider)
    if reason is not None:
        return reason
    words = ", ".join(provider.capabilities())
    return f"{words}, always on" if provider is BUILTIN else words


def build_page(parent: QWidget | None, *, theme: ThemeService) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AppearanceSettingsPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    caption = QLabel("Theme providers", page)
    caption.setObjectName("InspectorCaption")
    layout.addWidget(caption)

    for provider in theme.providers:
        block = QWidget(page)
        block.setObjectName(f"ThemeProvider_{provider.id}")
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        if provider is BUILTIN:
            column.addWidget(QLabel(provider.label, block))
        else:
            box = QCheckBox(provider.label, block)
            box.setObjectName(f"ThemeProviderBox_{provider.id}")
            refused = theme.refusal(provider) is not None
            box.setChecked(theme.enabled(provider) and not refused)
            box.setEnabled(not refused)
            box.toggled.connect(
                lambda on, provider_id=provider.id: theme.set_enabled(provider_id, bool(on))
            )
            column.addWidget(box)
        note = QLabel(provider_words(provider, theme), block)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        column.addWidget(note)
        layout.addWidget(block)
    layout.addStretch(1)
    return page
