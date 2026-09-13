"""The "Appearance" settings page: every theme provider, and a switch for each.

Per user, per machine — a GLOBAL-scope preference: which providers this person wants
offered. A provider that does not apply here shows its reason under a box that cannot be
ticked; the built-in one is a line rather than a box, since a switch that cannot be turned
off is a control that teaches nothing (DESIGN.md's *Words*).
"""

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from dplanner.framework.settings_registry import settings_page
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import block, caption, note
from dplanner.theme.providers import BUILTIN, ThemeProvider
from dplanner.theme.tokens import ROW_LINE_GAP, SECTION_GAP


def provider_words(provider: ThemeProvider, theme: ThemeService) -> str:
    """The line under a provider: why it is not offered here, else what it can do."""
    reason = theme.refusal(provider)
    if reason is not None:
        return reason
    words = ", ".join(provider.capabilities())
    return f"{words}, always on" if provider is BUILTIN else words


def build_page(parent: QWidget | None, *, theme: ThemeService) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("AppearanceSettingsPage")

    # One block: the caption over the providers, each a box (or a line) over what it can
    # do here — a two-line row, the second line a note because it changes with the machine.
    providers = QWidget(page)
    rows = QVBoxLayout(providers)
    rows.setContentsMargins(0, 0, 0, 0)
    rows.setSpacing(SECTION_GAP)
    for provider in theme.providers:
        row = QWidget(providers)
        row.setObjectName(f"ThemeProvider_{provider.id}")
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ROW_LINE_GAP)
        if provider is BUILTIN:
            column.addWidget(QLabel(provider.label, row))
        else:
            box = QCheckBox(provider.label, row)
            box.setObjectName(f"ThemeProviderBox_{provider.id}")
            refused = theme.refusal(provider) is not None
            box.setChecked(theme.enabled(provider) and not refused)
            box.setEnabled(not refused)
            box.toggled.connect(
                lambda on, provider_id=provider.id: theme.set_enabled(provider_id, bool(on))
            )
            column.addWidget(box)
        column.addWidget(note(provider_words(provider, theme), row))
        rows.addWidget(row)
    block(layout, caption("Theme providers", page), providers)
    layout.addStretch(1)
    return page
