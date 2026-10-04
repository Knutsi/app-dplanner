"""``modules/openai/dictation.py``: the batch endpoint and the live session, over a
scripted socket and a stubbed client — no key, no network."""

import queue
import threading
from pathlib import Path
from typing import Any

import keyring
import pytest

from dplanner.modules.openai import dictation as openai_dictation
from dplanner.modules.openai.dictation import (
    BATCH,
    COMMITTED,
    COMPLETED,
    DELTA,
    LIVE,
    NO_KEY,
    SETUP_ACTION,
    LiveSession,
)


@pytest.fixture
def stored(monkeypatch):
    keys: dict[str, str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda _service, user: keys.get(user))
    return keys


class Socket:
    """A Realtime connection stand-in: what was sent, and a script of what to answer."""

    def __init__(self, script=()):
        self.sent: list[dict[str, Any]] = []
        self.answers: queue.Queue[Any] = queue.Queue()
        self.closed = threading.Event()
        for event in script:
            self.answers.put(event)

    def send(self, event):
        self.sent.append(event)
        if event["type"] == "input_audio_buffer.commit":
            self.answers.put({"type": COMMITTED, "item_id": "last"})
            self.answers.put({"type": COMPLETED, "item_id": "last", "transcript": "and done"})

    def recv(self):
        event = self.answers.get()
        if event is None:
            raise ConnectionError("closed")
        return event

    def close(self):
        self.closed.set()
        self.answers.put(None)


def test_both_providers_refuse_without_a_key_and_name_the_action_that_mends_it(stored):
    for provider in (BATCH, LIVE):
        assert provider.refusal(provider.default) == NO_KEY
        assert provider.setup_action == SETUP_ACTION and provider.needs_setup
    stored["llm_openai.api_key"] = "sk-test"
    assert BATCH.refusal(BATCH.default) is None and LIVE.refusal(LIVE.default) is None
    assert (BATCH.live, LIVE.live, LIVE.rate) == (False, True, 24000)


def test_the_sdk_is_imported_only_inside_the_two_working_functions():
    """``dplanner checklist show`` reads the providers; the SDK must not come with them."""
    source = Path(openai_dictation.__file__).read_text(encoding="utf-8")
    head = source[: source.index("def transcribe(")]
    assert "from openai" not in head and "import openai" not in head


def test_batch_sends_the_clip_as_a_named_wav_with_text_format_and_the_chosen_model(
    stored, monkeypatch
):
    stored["llm_openai.api_key"] = "sk-test"
    calls = []

    class Transcriptions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return "  Hello there.  "

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.audio = type("Audio", (), {"transcriptions": Transcriptions()})()

    monkeypatch.setattr("openai.OpenAI", Client)

    assert BATCH.transcribe is not None
    assert BATCH.transcribe(b"RIFFwav", "gpt-4o-mini-transcribe") == "Hello there."
    assert calls[0]["api_key"] == "sk-test" and calls[0]["max_retries"] == 0
    assert calls[1] == {
        "model": "gpt-4o-mini-transcribe",
        "file": ("dictation.wav", b"RIFFwav"),
        "response_format": "text",
    }


def test_a_live_session_configures_transcription_feeds_audio_and_turns_events_into_deltas():
    socket = Socket(
        [
            {"type": "session.updated"},
            {"type": DELTA, "item_id": "one", "delta": "hello "},
            {"type": DELTA, "item_id": "one", "delta": "world"},
            {"type": COMMITTED, "item_id": "one"},
            {"type": COMPLETED, "item_id": "one", "transcript": "Hello world."},
        ]
    )
    heard: list[tuple[str, bool]] = []

    session = LiveSession(
        socket, "gpt-4o-transcribe", lambda text, final: heard.append((text, final))
    )
    session.feed(b"\x00\x01" * 8)
    session.finish()

    first = socket.sent[0]
    assert first["type"] == "session.update" and first["session"]["type"] == "transcription"
    audio_in = first["session"]["audio"]["input"]
    assert audio_in["format"] == {"type": "audio/pcm", "rate": 24000}
    assert audio_in["transcription"] == {"model": "gpt-4o-transcribe"}
    assert audio_in["turn_detection"] == {"type": "server_vad"}
    assert socket.sent[1] == {
        "type": "input_audio_buffer.append",
        "audio": "AAEAAQABAAEAAQABAAEAAQ==",
    }
    assert socket.sent[2] == {"type": "input_audio_buffer.commit"}
    assert heard == [
        ("hello ", False),
        ("world", False),
        ("Hello world.", True),
        ("and done", True),
    ]
    assert socket.closed.is_set()


def test_a_commit_over_an_empty_buffer_is_not_a_failure():
    class Quiet(Socket):
        def send(self, event):
            self.sent.append(event)
            if event["type"] == "input_audio_buffer.commit":
                self.answers.put(
                    {
                        "type": "error",
                        "error": {
                            "message": "Error committing input audio buffer: buffer too small."
                        },
                    }
                )

    session = LiveSession(Quiet(), "m", lambda *_: None)
    session.finish()  # Returns rather than raising.


def test_an_api_error_reaches_the_feeder_and_the_finisher():
    socket = Socket([{"type": "error", "error": {"message": "invalid api key"}}])
    session = LiveSession(socket, "m", lambda *_: None)
    import time

    time.sleep(0.1)
    with pytest.raises(RuntimeError, match="invalid api key"):
        session.feed(b"\x00\x01")
    with pytest.raises(RuntimeError, match="invalid api key"):
        session.finish()


def test_finish_waits_only_a_bounded_time_for_a_transcript_that_never_comes(monkeypatch):
    monkeypatch.setattr(openai_dictation, "FINISH_TIMEOUT_S", 0.2)

    class Silent(Socket):
        def send(self, event):
            self.sent.append(event)
            if event["type"] == "input_audio_buffer.commit":
                self.answers.put({"type": COMMITTED, "item_id": "x"})  # ...and never completed.

    session = LiveSession(Silent(), "m", lambda *_: None)
    session.finish()
    assert session._pending == 1  # Gave up waiting, closed anyway.


def test_listen_connects_with_the_stored_key(stored):
    stored["llm_openai.api_key"] = "sk-live"
    seen = []

    def connect(key):
        seen.append(key)
        return Socket()

    session = openai_dictation.listen("m", lambda *_: None, connect=connect)
    session.finish()
    assert seen == ["sk-live"]
