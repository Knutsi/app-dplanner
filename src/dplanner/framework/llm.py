"""Pluggable LLM providers: modules register one at startup, like an export format.

The registry only knows the id/label vocabulary of providers — picking one and running a
prompt through it is :class:`~dplanner.framework.llm_service.LLMService`'s job, which is the
face other modules actually depend on (see that module's docstring for why the split).
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int


class LLMTimeoutError(RuntimeError):
    """The provider's request timed out — a distinct outcome, not a generic failure."""


@runtime_checkable
class LLMProvider(Protocol):
    id: str
    label: str

    def is_configured(self) -> bool:
        """Whether this provider has what it needs (an API key, at minimum) to run."""
        ...

    def model(self) -> str:
        """The configured model name, for display."""
        ...

    def complete(self, messages: list[LLMMessage]) -> LLMResult:
        """Run a prompt and return the completion. BLOCKING network I/O — callers must
        run this off the GUI thread (see LLMService's docstring). Raises
        :class:`LLMTimeoutError` when the request exceeds the provider's time budget."""
        ...


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        if provider.id in self._providers:
            raise ValueError(f"LLM provider {provider.id!r} already registered")
        self._providers[provider.id] = provider

    def providers(self) -> list[LLMProvider]:
        """All providers, in registration order."""
        return list(self._providers.values())

    def get(self, provider_id: str) -> LLMProvider | None:
        return self._providers.get(provider_id)
