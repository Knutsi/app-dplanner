"""The LLM module: no provider of its own — just the "pick your preferred provider"
Settings page over whatever OpenAI/Anthropic/future provider modules have registered."""

from dataclasses import dataclass

from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.settings_registry import (
    SettingsScope,
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.modules.llm.settings_page import build_page

MODULE_ID = "llm"


@dataclass(frozen=True)
class LlmDeps:
    llm_providers: LLMProviderRegistry
    llm: LLMService
    settings_sections: SettingsSectionRegistry


class LlmModule:
    id = MODULE_ID

    def __init__(self, deps: LlmDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.settings_sections.register(
            SettingsSection(
                id="llm.preferred",
                category=("LLM",),
                scope=SettingsScope.GLOBAL,
                factory=lambda parent: build_page(deps.llm_providers, deps.llm, parent),
            )
        )
