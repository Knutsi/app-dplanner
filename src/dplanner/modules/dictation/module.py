"""The dictation module: Settings ▸ Dictation and the action that opens it.

No provider of its own, the ``llm`` module's arrangement: the providers are other modules'
Qt-free records, the service is the framework's, and this module is the page that picks
among them and the verb a refusal names as its mend — the checklist's rows and the
microphone's own words both say *Set Up Dictation…*.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import ContextService
from dplanner.framework.dictation import DictationService
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.modules.dictation.checks import SETUP_ACTION
from dplanner.modules.dictation.settings_page import build_page

MODULE_ID = "dictation"
SETTINGS_SECTION = "dictation.setup"


@dataclass(frozen=True)
class DictationDeps:
    dictation: DictationService
    settings_sections: SettingsSectionRegistry
    actions: ActionRegistry
    context: ContextService  # The page runs a provider's setup action against the live context.
    open_settings: Callable[[str], None] = field(default=lambda _section_id: None)


class DictationModule:
    id = MODULE_ID

    def __init__(self, deps: DictationDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def run_action(action_id: str) -> None:
            deps.actions.run(action_id, deps.context.current())

        deps.settings_sections.register(
            SettingsSection(
                id=SETTINGS_SECTION,
                category=("Dictation",),
                factory=lambda parent: build_page(deps.dictation, parent, run_action=run_action),
            )
        )
        deps.actions.register(
            ActionSpec(
                id=SETUP_ACTION,
                label="Set Up &Dictation…",
                menu="Tools",
                group="install",
                order=50,
                in_menus=False,  # The palette, a checklist row and a greyed microphone reach it.
                tip="Settings ▸ Dictation: the provider that transcribes and the recorder",
                run=lambda _context: deps.open_settings(SETTINGS_SECTION),
            )
        )
