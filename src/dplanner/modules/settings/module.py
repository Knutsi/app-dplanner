"""Settings: a tree-based dialog over module-contributed sections.

The dialog renders whatever the registry holds and knows nothing about any particular
setting. This module's own job is to open it — the File menu entry and its shortcut, and
:meth:`SettingsModule.open` on a section for a surface that deep-links to the page that
configures it (the composition root hands it over as a callback; modules never import
each other).

There is deliberately no settings *schema*. Each section owns how it reads and writes its
own values — through ``user_config`` for preferences, ``core/secrets`` for credentials —
because there is nothing generic to say about that.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.settings_registry import (
    SettingsSectionRegistry,
)
from dplanner.modules.settings.dialog import SettingsDialog

MODULE_ID = "settings"


@dataclass(frozen=True)
class SettingsDeps:
    actions: ActionRegistry
    settings_sections: SettingsSectionRegistry
    parent: QWidget  # The dialog's parent.


class SettingsModule:
    id = MODULE_ID

    def __init__(self, deps: SettingsDeps) -> None:
        self._deps = deps

    def open(self, section_id: str | None = None) -> None:
        if section_id is not None:
            self.dialog.show_section(section_id)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def register(self) -> None:
        deps = self._deps
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
