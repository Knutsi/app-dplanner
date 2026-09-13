"""OpenAI as two dictation providers, on the key this module already keeps.

**Batch** sends the clip to the transcription endpoint once the microphone is off and gets
the words back in one piece. **Live** opens a Realtime session in transcription mode and
feeds it the samples as they are captured: the words arrive as deltas while the person is
still speaking, and each utterance's completed transcript replaces the deltas that led to
it (``server_vad`` cuts the stream into utterances). Both read the key
``core/secrets`` keeps under this module's id — the same one the LLM provider runs on —
and neither imports the SDK until it is asked to work, so ``dplanner checklist show``
stays a directory read.

**The socket is a seam.** :class:`LiveSession` speaks the Realtime events over anything
with ``send``, ``recv`` and ``close``; the SDK's connection is what the provider hands it,
a scripted one is what a test does. Feeding happens on the dictation worker and reading on
a thread of its own, because a ``recv`` blocks and an ``append`` must not wait for it.
"""

import base64
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from dplanner.core.secrets import get_secret
from dplanner.domain.dictation import Deltas, DictationProvider

MODULE_ID = "llm_openai"  # The stored id: the keychain and user_config know it by this.
KEY = "api_key"
BATCH_MODEL = "gpt-4o-mini-transcribe"
LIVE_MODEL = "gpt-4o-transcribe"
LIVE_RATE = 24000  # The Realtime API's pcm16 rate.
REQUEST_TIMEOUT_S = 120.0
FINISH_TIMEOUT_S = 10.0  # How long the last utterance's transcript is waited for.
KEYS_URL = "https://platform.openai.com/api-keys"
NO_KEY = "OpenAI has no API key — add one"
SETUP_ACTION = "llm_openai.key"

# What every Realtime event this session cares about is called.
DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"
FAILED = "conversation.item.input_audio_transcription.failed"
COMMITTED = "input_audio_buffer.committed"
ERROR = "error"


class Socket(Protocol):
    """What :class:`LiveSession` needs of a Realtime connection."""

    def send(self, event: Any) -> None: ...
    def recv(self) -> Any: ...
    def close(self) -> None: ...


type Connect = Callable[[str], Socket]  # The key in, an open connection out.


def _refusal(_text: str) -> str | None:
    return None if get_secret(MODULE_ID, KEY) else NO_KEY


def _key() -> str:
    key = get_secret(MODULE_ID, KEY)
    if not key:
        raise RuntimeError("OpenAI provider is not configured (no API key)")
    return key


def transcribe(wav: bytes, model: str) -> str:
    """The clip, transcribed in one request. BLOCKING; a worker thread's."""
    from openai import OpenAI

    client = OpenAI(api_key=_key(), timeout=REQUEST_TIMEOUT_S, max_retries=0)
    said = client.audio.transcriptions.create(
        model=model, file=("dictation.wav", wav), response_format="text"
    )
    return str(said).strip()


def _connect(key: str) -> Socket:
    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    return client.realtime.connect(extra_query={"intent": "transcription"}).enter()


def session_update(model: str) -> dict[str, Any]:
    """The one event that turns a fresh Realtime connection into a transcription session."""
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": LIVE_RATE},
                    "transcription": {"model": model},
                    "turn_detection": {"type": "server_vad"},
                }
            },
        },
    }


def _field(event: Any, name: str) -> Any:
    return event.get(name) if isinstance(event, dict) else getattr(event, name, None)


class LiveSession:
    """One live transcription over one socket: feed samples, hear words, finish."""

    def __init__(self, socket: Socket, model: str, on_delta: Deltas) -> None:
        self._socket = socket
        self._on_delta = on_delta
        self._pending = 0  # Utterances committed and not yet transcribed.
        self._committing = False  # Our own commit is out, and its acknowledgement awaited.
        self._acked = False
        self._settled = threading.Condition()
        self._closed = False
        self._error: str | None = None
        socket.send(session_update(model))
        self._reader = threading.Thread(target=self._read, name="dictation-live", daemon=True)
        self._reader.start()

    def feed(self, pcm: bytes) -> None:
        if self._error is not None:
            raise RuntimeError(self._error)
        audio = base64.b64encode(pcm).decode("ascii")
        self._socket.send({"type": "input_audio_buffer.append", "audio": audio})

    def finish(self) -> None:
        """Commit what is buffered, wait a bounded time for its transcript, close."""
        try:
            if self._error is None:
                with self._settled:
                    self._committing = True
                self._socket.send({"type": "input_audio_buffer.commit"})
                deadline = time.monotonic() + FINISH_TIMEOUT_S
                with self._settled:
                    while not self._done():
                        left = deadline - time.monotonic()
                        if left <= 0 or not self._settled.wait(left):
                            break
        finally:
            self._closed = True
            self._socket.close()
            self._reader.join(timeout=2.0)
        if self._error is not None:
            raise RuntimeError(self._error)

    def _done(self) -> bool:
        """Under the condition: the commit was answered and every utterance transcribed."""
        return self._error is not None or (self._acked and self._pending == 0)

    def _read(self) -> None:
        try:
            while not self._closed:
                self._on_event(self._socket.recv())
        except Exception as error:  # The socket closed, ours or theirs: the reader is done.
            if not self._closed:
                self._fail(str(error) or type(error).__name__)

    def _on_event(self, event: Any) -> None:
        kind = _field(event, "type")
        if kind == DELTA:
            self._on_delta(str(_field(event, "delta") or ""), False)
        elif kind == COMPLETED:
            self._on_delta(str(_field(event, "transcript") or "").strip(), True)
            self._settle(-1)
        elif kind == FAILED:
            self._settle(-1)
        elif kind == COMMITTED:
            self._settle(+1, acked=True)
        elif kind == ERROR:
            problem = _field(event, "error")
            message = str(_field(problem, "message") or problem or "the API refused")
            # A commit over an empty buffer is not a failure: nothing more was said.
            if "buffer" in message.lower() and "small" in message.lower():
                self._settle(0, acked=True)
                return
            self._fail(message)

    def _settle(self, change: int, *, acked: bool = False) -> None:
        with self._settled:
            self._pending = max(0, self._pending + change)
            if acked and self._committing:
                self._acked = True
            self._settled.notify_all()

    def _fail(self, message: str) -> None:
        with self._settled:
            self._error = message
            self._settled.notify_all()


def listen(model: str, on_delta: Deltas, *, connect: Connect = _connect) -> LiveSession:
    return LiveSession(connect(_key()), model, on_delta)


BATCH = DictationProvider(
    id="openai_api",
    label="OpenAI transcription",
    caption="Model",
    default=BATCH_MODEL,
    refusal=_refusal,
    transcribe=transcribe,
    hint="A transcription model on your OpenAI account; the clip is sent when you stop.",
    url=KEYS_URL,
    setup_action=SETUP_ACTION,
)

LIVE = DictationProvider(
    id="openai_live",
    label="OpenAI live transcription",
    caption="Model",
    default=LIVE_MODEL,
    refusal=_refusal,
    listen=listen,
    rate=LIVE_RATE,
    hint="A Realtime transcription model; the words land while you speak.",
    url=KEYS_URL,
    setup_action=SETUP_ACTION,
)
