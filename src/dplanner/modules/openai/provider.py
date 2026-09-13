"""The OpenAI LLMProvider: a thin adapter over the official SDK.

Reads its API key from the OS keychain (never from disk) and its model name from
namespaced global settings, both under this module's own id — nothing outside this file
needs to know OpenAI's request/response shape.

Reasoning models generate for minutes on a chapter-length prompt, so the request timeout
is generous and retries are off — a retried timeout would multiply the wait invisibly
while the task looks stuck.
"""

from typing import Any, cast

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from dplanner.core.secrets import get_secret
from dplanner.framework.llm import LLMMessage, LLMResult, LLMTimeoutError
from dplanner.framework.user_config import get_global

MODULE_ID = "llm_openai"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"  # "" = never send the parameter.
REQUEST_TIMEOUT_SECONDS = 600.0

# Model ids the settings page's picker hides: not chat models, or not meant for prose
# (matched as substrings of the id).
_NON_CHAT_MARKERS = (
    "audio",
    "babbage",
    "codex",
    "davinci",
    "embedding",
    "image",
    "instruct",
    "live",
    "moderation",
    "realtime",
    "search",
    "sora",
    "transcribe",
    "tts",
    "whisper",
)


def current_model() -> str:
    return str(get_global(MODULE_ID, "model", DEFAULT_MODEL))


def current_reasoning_effort() -> str:
    return str(get_global(MODULE_ID, "reasoning_effort", DEFAULT_REASONING_EFFORT))


def _client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)


def list_chat_models() -> list[str]:
    """The account's chat-capable model ids, for the settings page's picker. BLOCKING
    network I/O — call off the GUI thread. Raises on a missing key or API failure."""
    api_key = get_secret(MODULE_ID, "api_key")
    if not api_key:
        raise RuntimeError("OpenAI provider is not configured (no API key)")
    ids = (model.id for model in _client(api_key).models.list())
    return sorted(
        model_id for model_id in ids if not any(marker in model_id for marker in _NON_CHAT_MARKERS)
    )


PROBE_TIMEOUT_SECONDS = 30.0
KEYS_URL = "https://platform.openai.com/api-keys"
KEY_GUIDE = (
    "1. Open OpenAI's API keys page (the button below) and create a secret key for this "
    "computer. It is shown once; copy it then.\n"
    "2. Paste it here and test it — the test lists the models the key can reach, and "
    "nothing is billed.\n"
    "3. Save. The key is kept in this computer's keychain — never in the plan, never in "
    "a file — and both the LLM and the dictation providers run on it."
)


def probe_key(api_key: str) -> str:
    """What ``api_key`` can reach, in words — or the SDK's own refusal, raised. BLOCKING."""
    client = OpenAI(api_key=api_key, timeout=PROBE_TIMEOUT_SECONDS, max_retries=0)
    count = sum(1 for _model in client.models.list())
    return f"{count} models on the account"


class OpenAIProvider:
    id = "openai"
    label = "OpenAI"

    def is_configured(self) -> bool:
        return bool(get_secret(MODULE_ID, "api_key"))

    def model(self) -> str:
        return current_model()

    def complete(self, messages: list[LLMMessage]) -> LLMResult:
        api_key = get_secret(MODULE_ID, "api_key")
        if not api_key:
            raise RuntimeError("OpenAI provider is not configured (no API key)")
        client = _client(api_key)
        kwargs: dict[str, Any] = {
            "model": current_model(),
            "messages": cast(
                "list[ChatCompletionMessageParam]",
                [{"role": message.role, "content": message.content} for message in messages],
            ),
        }
        if current_reasoning_effort():
            kwargs["reasoning_effort"] = current_reasoning_effort()
        try:
            try:
                response = client.chat.completions.create(**kwargs)
            except openai.BadRequestError as error:
                # Non-reasoning models reject the parameter outright; drop it and retry
                # so one effort setting works across the whole model list.
                if "reasoning_effort" not in kwargs or "reasoning_effort" not in str(error):
                    raise
                del kwargs["reasoning_effort"]
                response = client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as error:
            raise LLMTimeoutError(
                f"OpenAI request timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s"
            ) from error
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage is not None else 0
        tokens_out = usage.completion_tokens if usage is not None else 0
        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out)
