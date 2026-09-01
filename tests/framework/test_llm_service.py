"""The provider-agnostic LLM face: what it says when it cannot run, and what it records.

These are the tests the service went without while it had no consumer. They exist now
because the docs module is that consumer, and every rule it relies on is here: the three
refusal sentences an AI-gated control shows, the ring buffer *Debug ▸ LLM Calls* reads, and
the fact that a timeout is a distinct outcome rather than a generic failure.

A provider is satisfied structurally (``LLMProvider`` is a runtime-checkable Protocol), so
a fake is a plain class and no test here touches a network.
"""

import pytest

from dplanner.framework.llm import LLMMessage, LLMProviderRegistry, LLMResult, LLMTimeoutError
from dplanner.framework.llm_service import LLMService, LLMUnavailableError


class FakeProvider:
    def __init__(self, provider_id="fake", *, configured=True, answer="A document.", raises=None):
        self.id = provider_id
        self.label = provider_id.title()
        self._configured = configured
        self._answer = answer
        self._raises = raises
        self.seen: list[list[LLMMessage]] = []

    def is_configured(self):
        return self._configured

    def model(self):
        return "fake-1"

    def complete(self, messages):
        self.seen.append(list(messages))
        if self._raises is not None:
            raise self._raises
        return LLMResult(text=self._answer, tokens_in=11, tokens_out=22)


@pytest.fixture
def registry():
    return LLMProviderRegistry()


@pytest.fixture
def service(registry, monkeypatch):
    """A service over an empty registry, with the preference kept in memory.

    No ``qapp``: the service's own signal is ``core.signals.Signal``, and the one Qt thing
    it touches is the preference, which is patched here — so this exercises it with no
    graphics stack, which is also what keeps it from writing into the machine the suite
    runs on and racing another worker doing the same (the suite runs on every core).
    """
    stored: dict[str, object] = {}
    monkeypatch.setattr(
        "dplanner.framework.llm_service.get_global",
        lambda module, key, default=None: stored.get(f"{module}/{key}", default),
    )
    monkeypatch.setattr(
        "dplanner.framework.llm_service.set_global",
        lambda module, key, value: stored.__setitem__(f"{module}/{key}", value),
    )
    return LLMService(registry)


def prompt():
    return [LLMMessage(role="user", content="Write it")]


# -- what a disabled control shows -------------------------------------------------------------


def test_with_no_provider_chosen_it_names_where_to_choose_one(service):
    status = service.status()
    assert status.configured is False
    assert status.message == "No AI provider configured — choose one in Settings ▸ LLM"
    assert service.available() is False


def test_a_provider_without_a_key_says_so_by_name(service, registry):
    registry.register(FakeProvider("openai", configured=False))
    service.set_preferred_provider_id("openai")
    status = service.status()
    assert status.configured is False
    assert status.provider_label == "Openai"
    assert "no API key" in status.message and "Settings ▸ LLM" in status.message


def test_a_configured_provider_reports_its_model_and_nothing_to_say(service, registry):
    registry.register(FakeProvider("openai"))
    service.set_preferred_provider_id("openai")
    status = service.status()
    assert (status.configured, status.model, status.message) == (True, "fake-1", "")


def test_choosing_a_provider_announces_it_so_gated_controls_re_ask(service):
    seen = []
    service.config_changed.connect(lambda: seen.append(True))
    service.set_preferred_provider_id("openai")
    assert seen == [True]


def test_the_preference_is_re_read_per_call_not_cached(service, registry):
    """Flipping it in Settings takes effect on the very next prompt, with no restart."""
    first, second = FakeProvider("first"), FakeProvider("second")
    registry.register(first)
    registry.register(second)
    service.set_preferred_provider_id("first")
    service.complete(prompt())
    service.set_preferred_provider_id("second")
    service.complete(prompt())
    assert (len(first.seen), len(second.seen)) == (1, 1)


# -- running one -------------------------------------------------------------------------------


def test_an_unconfigured_service_refuses_before_it_records_anything(service):
    with pytest.raises(LLMUnavailableError):
        service.complete(prompt())
    assert service.recent_calls() == []


def test_a_completed_call_is_recorded_with_its_token_counts(service, registry):
    registry.register(FakeProvider("openai"))
    service.set_preferred_provider_id("openai")
    result = service.complete(prompt())
    assert result.text == "A document."
    (record,) = service.recent_calls()
    assert (record.status, record.tokens_in, record.tokens_out) == ("ok", 11, 22)
    assert record.response_text == "A document."
    assert record.duration_s is not None


def test_a_failing_provider_records_the_error_and_re_raises(service, registry):
    registry.register(FakeProvider("openai", raises=RuntimeError("502 upstream")))
    service.set_preferred_provider_id("openai")
    with pytest.raises(RuntimeError):
        service.complete(prompt())
    (record,) = service.recent_calls()
    assert (record.status, record.error_type) == ("error", "RuntimeError")
    assert record.error_message == "502 upstream"


def test_a_timeout_is_its_own_outcome_not_a_generic_failure(service, registry):
    registry.register(FakeProvider("openai", raises=LLMTimeoutError("took too long")))
    service.set_preferred_provider_id("openai")
    with pytest.raises(LLMTimeoutError):
        service.complete(prompt())
    assert service.recent_calls()[0].status == "timeout"


def test_an_http_status_is_lifted_off_whatever_the_sdk_raised(service, registry):
    """Duck-typed on purpose: framework/ must import neither SDK."""

    class RefusedError(RuntimeError):
        status_code = 429

    registry.register(FakeProvider("openai", raises=RefusedError("slow down")))
    service.set_preferred_provider_id("openai")
    with pytest.raises(RefusedError):
        service.complete(prompt())
    assert service.recent_calls()[0].http_status == 429


def test_the_buffer_keeps_the_last_hundred_calls(service, registry):
    registry.register(FakeProvider("openai"))
    service.set_preferred_provider_id("openai")
    for _ in range(105):
        service.complete(prompt())
    calls = service.recent_calls()
    assert len(calls) == 100
    # Oldest first, and the ids are monotonic — a stable key for the GUI across snapshots.
    assert [call.call_id for call in calls] == list(range(6, 106))


def test_a_snapshot_is_copies_so_a_worker_cannot_be_caught_half_written(service, registry):
    registry.register(FakeProvider("openai"))
    service.set_preferred_provider_id("openai")
    service.complete(prompt())
    snapshot = service.recent_calls()[0]
    snapshot.status = "tampered"
    assert service.recent_calls()[0].status == "ok"
