"""``framework/dictation.py``: the service's answers and the state machine's turns, over a
fake provider and the fake recorder."""

import sys
import threading
import time

import pytest
from tests.framework.fake_recorder import command_text, wait_for

from dplanner.domain.dictation import DictationProvider, Recorder
from dplanner.framework import dictation as service_mod
from dplanner.framework.dictation import BUSY, NO_PROVIDER, Dictation, DictationService
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import set_global

HERE = Recorder("fake", "Fake recorder", "linux", command_text(), "python-fake")
QUIET = Recorder("quiet", "Quiet recorder", "linux", command_text("quiet"), "python-quiet")
FOUND = {"python-fake": "/usr/bin/x", "python-quiet": "/usr/bin/y", sys.executable: sys.executable}


class Batch:
    """A batch provider that answers with what it was handed."""

    def __init__(self, answer: str = "hello world", *, raises=None, delay=0.0):
        self.answer, self.raises, self.delay = answer, raises, delay
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, wav: bytes, text: str) -> str:
        self.calls.append((wav, text))
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        return self.answer


class Live:
    """A live provider: a word per chunk fed, and a final transcript when finished."""

    def __init__(self, *, fail_on_open=False):
        self.fail_on_open = fail_on_open
        self.fed = 0
        self.finished = threading.Event()

    def listen(self, text, on_delta):
        if self.fail_on_open:
            raise RuntimeError("no socket")
        provider = self

        class Session:
            def feed(self, pcm):
                provider.fed += 1
                if provider.fed <= 3:
                    on_delta(f"word{provider.fed} ", False)

            def finish(self):
                on_delta("the final words", True)
                provider.finished.set()

        return Session()


def batch_provider(engine=None, *, refusal=None, provider_id="fake", default="fake --model x"):
    engine = engine or Batch()
    return DictationProvider(
        id=provider_id,
        label="Fake engine",
        caption="Command",
        default=default,
        refusal=lambda _text: refusal,
        transcribe=engine.transcribe,
    )


def live_provider(engine=None, *, provider_id="live"):
    engine = engine or Live()
    return DictationProvider(
        id=provider_id,
        label="Fake live",
        caption="Model",
        default="live-1",
        refusal=lambda _text: None,
        listen=engine.listen,
        rate=24000,
    )


def pump(app, seconds=0.05):
    """Let a recording run for a moment."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def recorded(app, made):
    """Wait until the recorder has handed over some samples: a clip a stop can act on."""
    wait_for(app, lambda: made.bytes_recorded() > 0 or made.state() == "idle", what="the clip")


def service(*providers, recorders=(HERE,), which=FOUND.get, platform="linux"):
    return DictationService(
        providers, TaskService(), recorders=recorders, which=which, platform=platform
    )


@pytest.fixture
def scribe(app):
    """A Dictation over a batch provider, with everything it says written down."""

    def make(*providers, **kwargs):
        made = Dictation(service(*providers, **kwargs))
        heard: list[tuple[str, bool]] = []
        states: list[str] = []
        refusals: list[str] = []
        made.heard.connect(lambda text, final: heard.append((text, final)))
        made.state_changed.connect(states.append)
        made.refused.connect(refusals.append)
        keep.append(made)
        return made, heard, states, refusals

    keep: list[Dictation] = []
    yield make
    for made in keep:
        made.abandon()
        made.deleteLater()


# -- the service -----------------------------------------------------------------------------


def test_a_build_with_no_providers_refuses_with_the_build_reason():
    status = service().status()
    assert (status.ready, status.message) == (False, NO_PROVIDER)


def test_nothing_picked_means_whatever_is_ready_here_dictates():
    """``choice`` says which provider is picked — the first, until somebody picks — and
    ``status`` says what works: with nothing picked, the first provider that does."""
    first, second = batch_provider(refusal="not on PATH", provider_id="a"), batch_provider()
    made = service(first, second)

    assert made.choice() == (first, "fake --model x") and not made.picked()
    status = made.status()
    assert status.ready and status.provider is second and status.recorder[0] == sys.executable
    made.set_choice("a", "")
    assert made.picked() and not made.status().ready  # Picked on purpose: it refuses in words.


def test_a_stored_choice_and_its_text_are_read_back_and_kept_per_provider():
    made = service(batch_provider(provider_id="a"), batch_provider(provider_id="b"))

    made.set_choice("b", " b --tuned ")
    made.set_choice("a", "a --tuned")
    assert made.choice() == (made.providers[0], "a --tuned")
    assert made.texts() == {"b": "b --tuned", "a": "a --tuned"}
    made.set_choice("b", "")
    assert made.choice() == (made.providers[1], "fake --model x")  # Empty means the default.


def test_a_stored_id_this_build_does_not_have_falls_back():
    set_global("dictation", "provider", "gone")
    made = service(batch_provider())
    assert made.choice() == (made.providers[0], "fake --model x")


def test_status_is_memoised_and_re_read_on_config_changed():
    asked: list[str] = []

    def refusal(text: str) -> str | None:
        asked.append(text)
        return None

    provider = DictationProvider("p", "P", "Command", "p", refusal, transcribe=Batch().transcribe)
    made = service(provider)

    made.status()
    made.status()
    assert len(asked) == 1
    made.config_changed.emit()
    made.status()
    assert len(asked) == 2


def test_a_refusing_provider_and_a_missing_recorder_are_said_with_where_to_mend_them():
    refused = service(batch_provider(refusal="whisper-cli is not on PATH")).status()
    assert not refused.ready and refused.message == (
        "Fake engine: whisper-cli is not on PATH — Settings ▸ Dictation"
    )
    no_recorder = service(batch_provider(), which=lambda _name: None).status()
    assert not no_recorder.ready and no_recorder.message.startswith("Cannot record: no recorder")

    typed = service(batch_provider())
    typed.set_recorder_command("nope --raw")
    assert typed.status().message == "Cannot record: nope is not on PATH — Settings ▸ Dictation"


def test_automatic_is_the_first_installed_row_and_a_typed_command_wins():
    made = service(batch_provider(), recorders=(QUIET, HERE))

    assert made.automatic_recorder() is QUIET
    assert made.recorder_refusal() is None
    assert made.rendered_recorder(16000)[-1] == "quiet"
    made.set_recorder_command(command_text("q") + " --rate {rate}")
    assert made.rendered_recorder(24000, made.recorder_command())[-2:] == ("--rate", "24000")
    assert made.status().recorder[-1] == "16000"  # The provider's rate, not the page's.


def test_only_this_platforms_recorders_are_offered():
    mac = Recorder("mac", "Mac", "darwin", "sox -", "sox")
    made = service(batch_provider(), recorders=(HERE, mac), platform="darwin", which=lambda n: "/x")
    assert made.recorders() == (mac,)


# -- the state machine, batch --------------------------------------------------------------


def test_toggle_records_then_transcribes_then_hears_the_transcript(app, scribe):
    engine = Batch("hello world")
    made, heard, states, refusals = scribe(batch_provider(engine))

    made.toggle()
    assert made.state() == "recording"
    recorded(app, made)
    made.toggle()
    assert made.state() == "transcribing"
    wait_for(app, lambda: made.state() == "idle", what="the transcription")

    assert heard == [("hello world", True)]
    assert states == ["recording", "transcribing", "idle"]
    assert refusals == []
    wav, text = engine.calls[0]
    assert wav[:4] == b"RIFF" and text == "fake --model x"


def test_a_silent_clip_is_refused_before_the_provider_is_asked(app, scribe):
    engine = Batch()
    made, heard, _states, refusals = scribe(batch_provider(engine, default="x"), recorders=(QUIET,))

    made.toggle()
    recorded(app, made)
    made.toggle()
    wait_for(app, lambda: made.state() == "idle", what="the silence check")

    assert engine.calls == [] and heard == []
    assert refusals == [service_mod.NOTHING_HEARD]


def test_a_provider_that_raises_refuses_with_its_words_and_the_task_ends(app, scribe):
    engine = Batch(raises=RuntimeError("model file missing"))
    made, heard, _states, refusals = scribe(batch_provider(engine))

    made.toggle()
    recorded(app, made)
    made.toggle()
    wait_for(app, lambda: made.state() == "idle", what="the failure")
    wait_for(app, lambda: not made.service.is_busy(), what="the failed task")

    assert heard == [] and refusals == ["model file missing"]


def test_a_second_dictation_while_one_transcribes_is_refused_as_busy(app, scribe):
    engine = Batch(delay=3.0)
    first, _heard, _states, refusals = scribe(batch_provider(engine))
    second = Dictation(first.service)
    seconds: list[str] = []
    second.refused.connect(seconds.append)

    first.toggle()
    recorded(app, first)
    first.toggle()
    wait_for(app, lambda: first.state() == "transcribing")
    wait_for(app, lambda: first.service.is_busy(), what="the runner")
    second.toggle()

    assert seconds == [BUSY] and refusals == []
    wait_for(app, lambda: first.state() == "idle", timeout=10.0)
    second.deleteLater()


def test_a_refusing_status_says_why_and_starts_nothing(scribe):
    made, _heard, states, refusals = scribe(batch_provider(refusal="not on PATH"))

    made.toggle()

    assert states == [] and refusals == ["Fake engine: not on PATH — Settings ▸ Dictation"]


def test_abandon_mid_recording_discards_the_clip(app, scribe):
    engine = Batch()
    made, heard, states, refusals = scribe(batch_provider(engine))

    made.toggle()
    recorded(app, made)
    made.abandon()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)

    assert states == ["recording", "idle"] and heard == [] and refusals == []
    assert engine.calls == []


def test_abandon_mid_transcription_drops_the_transcript_and_still_finishes_the_task(app, scribe):
    engine = Batch(delay=0.3)
    made, heard, _states, _refusals = scribe(batch_provider(engine))

    made.toggle()
    recorded(app, made)
    made.toggle()
    wait_for(app, lambda: made.service.is_busy())
    made.abandon()
    wait_for(app, lambda: not made.service.is_busy(), what="the abandoned task")

    assert heard == [] and made.state() == "idle"


# -- the state machine, live -----------------------------------------------------------------


def test_a_live_session_hears_words_as_they_come_and_the_final_at_the_end(app, scribe):
    engine = Live()
    made, heard, states, refusals = scribe(live_provider(engine))

    made.toggle()
    assert made.state() == "listening"
    wait_for(app, lambda: len(heard) >= 3, what="the deltas")
    made.toggle()
    assert made.state() == "finishing"
    wait_for(app, lambda: made.state() == "idle", what="the live finish")

    assert heard[:3] == [("word1 ", False), ("word2 ", False), ("word3 ", False)]
    assert heard[-1] == ("the final words", True)
    assert states == ["listening", "finishing", "idle"] and refusals == []
    assert engine.finished.is_set()


def test_a_live_session_that_cannot_open_refuses_and_stops_the_recorder(app, scribe):
    made, heard, _states, refusals = scribe(live_provider(Live(fail_on_open=True)))

    made.toggle()
    wait_for(app, lambda: made.state() == "idle", what="the failed open")

    assert heard == [] and refusals == ["no socket"]


def test_abandoning_a_live_session_ends_it_and_drops_late_words(app, scribe):
    engine = Live()
    made, heard, _states, _refusals = scribe(live_provider(engine))

    made.toggle()
    wait_for(app, lambda: len(heard) >= 1)
    made.abandon()
    wait_for(app, lambda: engine.finished.is_set(), what="the session's finish")
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)

    assert ("the final words", True) not in heard and made.state() == "idle"


def test_toggle_does_nothing_while_the_words_are_on_their_way(app, scribe):
    engine = Batch(delay=0.3)
    made, _heard, states, _refusals = scribe(batch_provider(engine))

    made.toggle()
    recorded(app, made)
    made.toggle()
    made.toggle()  # Transcribing: not a cancel.
    assert made.state() == "transcribing"
    wait_for(app, lambda: made.state() == "idle")
    assert states == ["recording", "transcribing", "idle"]
