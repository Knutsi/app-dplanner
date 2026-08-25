"""The provider-agnostic face other modules depend on: "is an LLM available" and "run a
prompt", without ever naming a concrete provider.

The preferred provider is a Global setting (``modules/llm``'s section writes it via
``user_config``); this service re-reads it on every call rather than caching, which is
what makes "change it on the fly" true — flipping the preference in Settings takes effect
on the very next prompt, no restart, no re-registration.

``complete()`` is BLOCKING (it is real network I/O to a third-party API) — same discipline
as ``GitService``: callers run it on a worker thread and marshal the result back via a Qt
signal, never call it from the GUI thread. Every call is recorded in a ring buffer of the
last 100 ``LLMCallRecord``s — appended as "running" before the provider runs, so a hung
request is visible — which the debug module's LLM Calls tab polls via ``recent_calls()``.
"""

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Literal

from dplanner.core.signals import Signal
from dplanner.framework.llm import (
    LLMMessage,
    LLMProvider,
    LLMProviderRegistry,
    LLMResult,
    LLMTimeoutError,
)
from dplanner.framework.user_config import get_global, set_global

_MODULE_ID = "llm"
_PREFERRED_KEY = "preferred_provider"

type LLMCallStatus = Literal["running", "ok", "error", "timeout"]


@dataclass  # Mutable on purpose: a record transitions running → final in place.
class LLMCallRecord:
    call_id: int  # Monotonic; a stable key for the GUI across snapshots.
    provider_id: str
    model: str
    request: tuple[LLMMessage, ...]
    started_at: float  # time.time() wall clock, for display.
    status: LLMCallStatus = "running"
    response_text: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_s: float | None = None  # None while running.
    error_type: str | None = None  # Exception class name.
    error_message: str | None = None
    http_status: int | None = None  # The SDKs' APIStatusError.status_code, when present.


class LLMUnavailableError(RuntimeError):
    """No provider is selected, or the selected one isn't configured (e.g. no API key)."""


# The one sentence every AI-gated control shows on its disabled face (tooltip etc.),
# so the wording stays identical across features.
AI_DISABLED_TIP = "AI functions are disabled until an AI service is configured"


@dataclass(frozen=True)
class LLMStatus:
    configured: bool
    provider_label: str | None
    model: str | None
    message: str  # "" when configured; a human-readable reason otherwise.


class LLMService:
    def __init__(self, registry: LLMProviderRegistry) -> None:
        self._registry = registry
        # ``complete()`` runs on worker threads, ``recent_calls()`` on the GUI thread —
        # hence the lock. Records are mutated in place under it.
        self._calls: deque[LLMCallRecord] = deque(maxlen=100)
        self._calls_lock = threading.Lock()
        self._call_ids = itertools.count(1)
        # LLM configuration changed (preferred provider, a provider's key or model) —
        # AI-gated widgets re-read status() on it. Emitted by the Settings pages and
        # set_preferred_provider_id, so always on the GUI thread.
        self.config_changed: Signal[()] = Signal()

    def preferred_provider_id(self) -> str | None:
        value = get_global(_MODULE_ID, _PREFERRED_KEY, None)
        return None if value is None else str(value)

    def set_preferred_provider_id(self, provider_id: str | None) -> None:
        set_global(_MODULE_ID, _PREFERRED_KEY, provider_id)
        self.config_changed.emit()

    def available(self) -> bool:
        return self.status().configured

    def status(self) -> LLMStatus:
        provider = self._current_provider()
        if provider is None:
            return LLMStatus(
                configured=False,
                provider_label=None,
                model=None,
                message="No AI provider configured — choose one in Settings ▸ LLM",
            )
        if not provider.is_configured():
            return LLMStatus(
                configured=False,
                provider_label=provider.label,
                model=None,
                message=f"{provider.label} has no API key — add one in Settings ▸ LLM",
            )
        return LLMStatus(
            configured=True,
            provider_label=provider.label,
            model=provider.model(),
            message="",
        )

    def recent_calls(self) -> list[LLMCallRecord]:
        """Snapshot of the last 100 calls, oldest first — copies, so the caller never
        sees a half-written mutation from a worker thread."""
        with self._calls_lock:
            return [replace(record) for record in self._calls]

    def complete(self, messages: list[LLMMessage]) -> LLMResult:
        provider = self._current_provider()
        if provider is None or not provider.is_configured():
            raise LLMUnavailableError("no LLM provider is selected and configured")
        record = LLMCallRecord(
            call_id=next(self._call_ids),
            provider_id=provider.id,
            model=provider.model(),
            request=tuple(messages),
            started_at=time.time(),
        )
        with self._calls_lock:
            self._calls.append(record)
        start = time.monotonic()
        try:
            result = provider.complete(messages)
        except LLMTimeoutError as error:
            self._finalize_error(record, start, "timeout", error)
            raise
        except Exception as error:
            self._finalize_error(record, start, "error", error)
            raise
        with self._calls_lock:
            record.status = "ok"
            record.response_text = result.text
            record.tokens_in = result.tokens_in
            record.tokens_out = result.tokens_out
            record.duration_s = time.monotonic() - start
        return result

    def _finalize_error(
        self, record: LLMCallRecord, start: float, status: LLMCallStatus, error: BaseException
    ) -> None:
        # Duck-typed: both openai's and anthropic's APIStatusError expose status_code,
        # and framework/ must not import either SDK.
        status_code = getattr(error, "status_code", None)
        with self._calls_lock:
            record.status = status
            record.duration_s = time.monotonic() - start
            record.error_type = type(error).__name__
            record.error_message = str(error)
            record.http_status = status_code if isinstance(status_code, int) else None

    def _current_provider(self) -> LLMProvider | None:
        provider_id = self.preferred_provider_id()
        if provider_id is None:
            return None
        return self._registry.get(provider_id)
