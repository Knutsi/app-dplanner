"""OpenAI as a vendor module: its LLM provider, its Settings page, and the one act every
provider needs first — adding the API key, walked through in a modal. The dictation
providers in ``dictation.py`` run on the same key. Nothing else in the app knows OpenAI
exists — everyone else goes through LLMService or DictationService."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.core.secrets import backend_problem, get_secret, set_secret
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.key_dialog import ApiKeyDialog
from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.framework.tasks import TaskService
from dplanner.modules.openai.provider import (
    KEY_GUIDE,
    KEYS_URL,
    MODULE_ID,
    OpenAIProvider,
    probe_key,
)
from dplanner.modules.openai.settings_page import build_page

KEY = "api_key"
KEY_ACTION = "openai.key"  # What a refusal names as its mend: the checklist's rule.
SETTINGS_SECTION = "llm.openai"


@dataclass(frozen=True)
class LlmOpenAIDeps:
    llm_providers: LLMProviderRegistry
    llm: LLMService  # The settings page and the key dialog announce edits via config_changed.
    settings_sections: SettingsSectionRegistry
    actions: ActionRegistry
    tasks: TaskService
    parent: QWidget  # The key dialog's parent.
    open_url: Callable[[str], None]


class LlmOpenAIModule:
    id = MODULE_ID

    def __init__(self, deps: LlmOpenAIDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.llm_providers.register(OpenAIProvider())
        deps.settings_sections.register(
            SettingsSection(
                id=SETTINGS_SECTION,
                category=("Providers", "OpenAI"),
                factory=lambda parent: build_page(deps.llm, parent),
            )
        )
        deps.actions.register(
            ActionSpec(
                id=KEY_ACTION,
                label="Add OpenAI API &Key…",
                menu="Tools",
                group="install",
                order=60,
                in_menus=False,  # Run from the palette, a provider's refusal or a checklist row.
                tip="Create or paste the OpenAI API key this computer uses, and test it",
                run=self.add_key,
            )
        )

    def add_key(self, _context: Context | None = None) -> None:
        """The guided modal; a tested key is saved and announced, a cancelled one forgotten."""
        deps = self._deps
        dialog = ApiKeyDialog(
            deps.parent,
            service="OpenAI",
            guide=KEY_GUIDE,
            keys_url=KEYS_URL,
            placeholder="sk-…",
            tasks=deps.tasks,
            probe=probe_key,
            open_url=deps.open_url,
            backend_problem=backend_problem(),
            current=get_secret(MODULE_ID, KEY) or "",
        )
        try:
            if dialog.exec() == ApiKeyDialog.DialogCode.Accepted and dialog.passed:
                set_secret(MODULE_ID, KEY, dialog.value())
                deps.llm.config_changed.emit()
        finally:
            dialog.deleteLater()
