"""Anthropic provider module: registers the provider and its Settings page. Nothing else
in the app knows Anthropic exists — everyone else goes through LLMService."""

from dataclasses import dataclass

from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.settings_registry import (
    SettingsScope,
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.modules.llm_anthropic.provider import AnthropicProvider
from dplanner.modules.llm_anthropic.settings_page import build_page

MODULE_ID = "llm_anthropic"


@dataclass(frozen=True)
class LlmAnthropicDeps:
    llm_providers: LLMProviderRegistry
    llm: LLMService  # The settings page announces key/model edits via config_changed.
    settings_sections: SettingsSectionRegistry


class LlmAnthropicModule:
    id = MODULE_ID

    def __init__(self, deps: LlmAnthropicDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.llm_providers.register(AnthropicProvider())
        deps.settings_sections.register(
            SettingsSection(
                id="llm.anthropic",
                category=("LLM Providers", "Anthropic"),
                scope=SettingsScope.GLOBAL,
                factory=lambda parent: build_page(deps.llm, parent),
            )
        )
