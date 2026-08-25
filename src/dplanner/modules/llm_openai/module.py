"""OpenAI provider module: registers the provider and its Settings page. Nothing else in
the app knows OpenAI exists — everyone else goes through LLMService."""

from dataclasses import dataclass

from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.settings_registry import (
    SettingsScope,
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.modules.llm_openai.provider import OpenAIProvider
from dplanner.modules.llm_openai.settings_page import build_page

MODULE_ID = "llm_openai"


@dataclass(frozen=True)
class LlmOpenAIDeps:
    llm_providers: LLMProviderRegistry
    llm: LLMService  # The settings page announces key/model edits via config_changed.
    settings_sections: SettingsSectionRegistry


class LlmOpenAIModule:
    id = MODULE_ID

    def __init__(self, deps: LlmOpenAIDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.llm_providers.register(OpenAIProvider())
        deps.settings_sections.register(
            SettingsSection(
                id="llm.openai",
                category=("LLM Providers", "OpenAI"),
                scope=SettingsScope.GLOBAL,
                factory=lambda parent: build_page(deps.llm, parent),
            )
        )
