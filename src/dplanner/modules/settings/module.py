"""Settings: a tree-based dialog over module-contributed sections.

The dialog renders whatever the registry holds and knows nothing about any particular
setting. This module's own job is to open it, to expose the deeplink other modules use
("AI settings…" jumping straight to the right page), and to register one General page so
the tree is never empty.

There is deliberately no settings *schema*. Each section owns how it reads and writes its
own values — through ``user_config`` for preferences, ``secrets_store`` for credentials, or
the workspace for project-scoped data — because there is nothing generic to say about that
which the two scopes do not already say.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.modules.settings.dialog import SettingsDialog

MODULE_ID = "settings"


@dataclass(frozen=True)
class SettingsDeps:
    actions: ActionRegistry
    settings_sections: SettingsSectionRegistry
    parent: QWidget  # The dialog's parent.


def _placeholder_page(parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("SettingsPlaceholderPage")
    layout = QVBoxLayout(page)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label = QLabel("Nothing here yet.", page)
    label.setObjectName("SettingsPlaceholderLabel")
    layout.addWidget(label)
    return page


class SettingsModule:
    id = MODULE_ID

    def __init__(self, deps: SettingsDeps) -> None:
        self._deps = deps

    def open(self) -> None:
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def register(self) -> None:
        deps = self._deps
        deps.settings_sections.register(
            SettingsSection(
                id="settings.general",
                category=("General",),
                factory=_placeholder_page,
            )
        )
        self.dialog = SettingsDialog(deps.settings_sections, deps.parent)

        def run_open(_context: Context) -> None:
            self.open()

        deps.actions.register(
            ActionSpec(
                id="settings.open",
                label="S&ettings…",
                menu="File",
                group="window",
                order=20,
                shortcut="Ctrl+,",
                tip="Application settings",
                run=run_open,
            )
        )
