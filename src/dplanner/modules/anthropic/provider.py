"""The Anthropic LLMProvider: a thin adapter over the official SDK.

Anthropic's API takes the system prompt as its own top-level parameter rather than a
"system" message in the list (unlike OpenAI) — this is the one place that shows through.
"""

from typing import cast

import anthropic
from anthropic.types import MessageParam, TextBlock

from dplanner.core.secrets import get_secret
from dplanner.framework.llm import LLMMessage, LLMResult, LLMTimeoutError
from dplanner.framework.user_config import get_global

MODULE_ID = "llm_anthropic"
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 120.0


def current_model() -> str:
    return str(get_global(MODULE_ID, "model", DEFAULT_MODEL))


def _split_system(messages: list[LLMMessage]) -> tuple[str, list[LLMMessage]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    rest = [m for m in messages if m.role != "system"]
    return system, rest


PROBE_TIMEOUT_SECONDS = 30.0
KEYS_URL = "https://console.anthropic.com/settings/keys"
KEY_GUIDE = (
    "1. Open the Anthropic console's API keys page (the button below) and create a key "
    "for this computer. It is shown once; copy it then.\n"
    "2. Paste it here and test it — the test lists the models the key can reach, and "
    "nothing is billed.\n"
    "3. Save. The key is kept in this computer's keychain — never in the plan, never in "
    "a file."
)


def probe_key(api_key: str) -> str:
    """What ``api_key`` can reach, in words — or the SDK's own refusal, raised. BLOCKING."""
    client = anthropic.Anthropic(api_key=api_key, timeout=PROBE_TIMEOUT_SECONDS)
    count = sum(1 for _model in client.models.list())
    return f"{count} models on the account"


class AnthropicProvider:
    id = "anthropic"
    label = "Anthropic"

    def is_configured(self) -> bool:
        return bool(get_secret(MODULE_ID, "api_key"))

    def model(self) -> str:
        return current_model()

    def complete(self, messages: list[LLMMessage]) -> LLMResult:
        api_key = get_secret(MODULE_ID, "api_key")
        if not api_key:
            raise RuntimeError("Anthropic provider is not configured (no API key)")
        system, rest = _split_system(messages)
        client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        chat_messages = cast(
            "list[MessageParam]",
            [{"role": message.role, "content": message.content} for message in rest],
        )
        try:
            response = client.messages.create(
                model=current_model(),
                max_tokens=MAX_TOKENS,
                system=system,
                messages=chat_messages,
            )
        except anthropic.APITimeoutError as error:
            raise LLMTimeoutError(
                f"Anthropic request timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s"
            ) from error
        text = "".join(block.text for block in response.content if isinstance(block, TextBlock))
        usage = response.usage
        tokens_in = usage.input_tokens if usage is not None else 0
        tokens_out = usage.output_tokens if usage is not None else 0
        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out)
