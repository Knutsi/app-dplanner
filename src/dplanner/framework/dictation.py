"""Dictation: the provider-agnostic face every microphone depends on, and the one state
machine behind all of them.

:class:`DictationService` is to :mod:`dplanner.domain.dictation` what ``LLMService`` is to
the LLM registry — "is dictation ready here" and "have this said", without naming an engine.
The chosen provider and recorder are per-user preferences (``user_config``), re-read when
they change; ``status()`` is memoised between changes because a dozen prose editors ask it
at every build, and one provider's refusal is a keychain round trip.

**The service owns the one task runner.** A transcription outlives the editor that asked
for it — a tab closed mid-sentence must not strand a *Transcribing…* row in the task centre
— so the runner is parented to the window, not to the strip, and every body captures only
plain values and a signal instance (``task_runner.py``'s rule): the receiver may be gone by
the time the answer comes, and a delivery to a deleted object is dropped, never a crash.
One microphone, one provider, one transcription at a time; a second editor pressing its
button while one runs is refused in words.

:class:`Dictation` is the state machine: idle → recording → transcribing → idle for a batch
provider, idle → listening → finishing → idle for a live one. The strip's verb and the
settings page's *Try it* are two faces of it, and neither knows a recorder from a provider.
A generation counter drops whatever a run delivers after :meth:`Dictation.abandon` — the
editor moved on to another step, or was torn down — so a late transcript never lands in
the wrong document.
"""

import contextlib
import queue
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QObject, Signal

from dplanner.core.signals import Signal as PlainSignal
from dplanner.core.wav import rms, wav_bytes
from dplanner.domain.dictation import (
    RECORDERS,
    DictationProvider,
    Recorder,
    Which,
    command_refusal,
    first_installed,
    provider_by_id,
    recorders_for,
    split_command,
)
from dplanner.framework.recording import Recording
from dplanner.framework.task_runner import TaskRunner, TaskTimeoutError
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import get_global, set_global

MODULE_ID = "dictation"
PROVIDER_KEY = "provider"  # user_config: the chosen provider's id.
TEXTS_KEY = "texts"  # user_config: {provider id: its text} — switching back keeps what was typed.
RECORDER_KEY = "recorder"  # user_config: the recorder command text; "" means Automatic.

NO_PROVIDER = "no dictation provider in this build"
WHERE = "Settings ▸ Dictation"
SILENCE_RMS = 0.004  # Below this share of full scale nothing was said: a floor over line noise.
NOTHING_HEARD = f"Nothing was heard — check the microphone under {WHERE}"
BUSY = "Dictation is busy in another editor"
TASK_KEY = "dictation"

type State = Literal["idle", "recording", "listening", "transcribing", "finishing"]
type Kind = Literal["delta", "final", "done", "error"]
Deliver = Callable[[str, str], None]  # (kind, text) — from the worker, to the GUI thread.


@dataclass(frozen=True)
class DictationStatus:
    ready: bool
    message: str  # "" when ready; the reason, naming where to mend it, otherwise.
    provider: DictationProvider | None = None
    text: str = ""  # The text the provider runs with: a command, a model.
    recorder: tuple[str, ...] = ()  # The recorder command, rendered for the provider's rate.


class DictationService:
    def __init__(
        self,
        providers: Sequence[DictationProvider],
        tasks: TaskService,
        *,
        recorders: Sequence[Recorder] = RECORDERS,
        platform: str = sys.platform,
        which: Which = shutil.which,
        parent: QObject | None = None,
    ) -> None:
        self.providers = tuple(providers)
        self._recorders = recorders_for(platform, recorders)
        self._which = which
        self._runner = TaskRunner(tasks, parent=parent)
        # A provider, a text or the recorder changed — every microphone re-asks status().
        # Emitted by the settings page and the setters, and by the builder when an LLM
        # provider's key changed, since the OpenAI providers read the same key.
        self.config_changed: PlainSignal[()] = PlainSignal()
        self._status: DictationStatus | None = None
        self.config_changed.connect(self._forget)

    # -- what is chosen --------------------------------------------------------------------

    def texts(self) -> dict[str, str]:
        stored = get_global(MODULE_ID, TEXTS_KEY, {})
        return {str(k): str(v) for k, v in stored.items()} if isinstance(stored, dict) else {}

    def choice(self) -> tuple[DictationProvider, str] | None:
        """The provider and the text it runs with: what was picked, else the first the
        build has. Says which, never whether it works — that is :meth:`status`."""
        texts = self.texts()
        picked = get_global(MODULE_ID, PROVIDER_KEY, None)
        provider = provider_by_id(self.providers, str(picked)) if picked is not None else None
        if provider is None and self.providers:
            provider = self.providers[0]
        if provider is None:
            return None
        return provider, texts.get(provider.id) or provider.default

    def picked(self) -> bool:
        """Whether somebody chose a provider, as against the build's first standing in."""
        return get_global(MODULE_ID, PROVIDER_KEY, None) is not None

    def set_choice(self, provider_id: str, text: str) -> None:
        set_global(MODULE_ID, PROVIDER_KEY, provider_id)
        set_global(MODULE_ID, TEXTS_KEY, {**self.texts(), provider_id: text.strip()})
        self.config_changed.emit()

    def recorders(self) -> tuple[Recorder, ...]:
        """This platform's rows, in the order Automatic tries them."""
        return self._recorders

    def automatic_recorder(self) -> Recorder | None:
        return first_installed(self._recorders, self._which)

    def recorder_command(self) -> str:
        """The stored command text; "" means Automatic."""
        return str(get_global(MODULE_ID, RECORDER_KEY, "") or "")

    def set_recorder_command(self, text: str) -> None:
        set_global(MODULE_ID, RECORDER_KEY, text.strip())
        self.config_changed.emit()

    def recorder_refusal(self, text: str = "") -> str | None:
        """Why the recorder text (or Automatic, for "") cannot run here."""
        if not text.strip():
            if self.automatic_recorder() is None:
                names = ", ".join(r.probe for r in self._recorders) or "none known here"
                return f"no recorder is installed ({names})"
            return None
        return command_refusal(text, self._which)

    def rendered_recorder(self, rate: int, text: str = "") -> tuple[str, ...]:
        """The command to run at ``rate``: the text, or Automatic's row."""
        chosen = text.strip()
        if not chosen:
            row = self.automatic_recorder()
            if row is None:
                return ()
            chosen = row.command
        try:
            return tuple(split_command(chosen, rate=str(rate)))
        except ValueError:
            return ()

    # -- what it adds up to ----------------------------------------------------------------

    def status(self) -> DictationStatus:
        if self._status is None:
            self._status = self._read_status()
        return self._status

    def _forget(self) -> None:
        self._status = None

    def _read_status(self) -> DictationStatus:
        if not self.providers:
            return DictationStatus(False, NO_PROVIDER)
        texts = self.texts()
        if self.picked():
            provider, text = self.choice() or (self.providers[0], self.providers[0].default)
            candidates = [(provider, text)]
        else:
            # Nothing chosen yet: whatever is ready on this machine dictates, so a fresh
            # profile works untouched wherever any provider does.
            candidates = [(p, texts.get(p.id) or p.default) for p in self.providers]
        refusals = []
        for provider, text in candidates:
            why = provider.refusal(text)
            if why is None:
                return self._recorded(provider, text)
            refusals.append(f"{provider.label}: {why}")
        provider, text = candidates[0]
        return DictationStatus(False, f"{'; '.join(refusals)} — {WHERE}", provider, text)

    def _recorded(self, provider: DictationProvider, text: str) -> DictationStatus:
        stored = self.recorder_command()
        why = self.recorder_refusal(stored)
        if why is not None:
            return DictationStatus(False, f"Cannot record: {why} — {WHERE}", provider, text)
        command = self.rendered_recorder(provider.rate, stored)
        if not command:
            return DictationStatus(
                False, f"Cannot read the recorder command — {WHERE}", provider, text
            )
        return DictationStatus(True, "", provider, text, command)

    # -- the work, off the GUI thread ------------------------------------------------------

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def run_transcription(
        self, provider: DictationProvider, text: str, wav: bytes, deliver: Deliver
    ) -> bool:
        """Have ``wav`` transcribed on the runner; ``deliver`` hears ``final`` then ``done``,
        or ``error``. False when a run is already going."""
        transcribe = provider.transcribe
        if transcribe is None:
            return False

        def body() -> None:
            try:
                said = transcribe(wav, text)
            except subprocess.TimeoutExpired as error:
                deliver("error", f"{provider.label} timed out")
                raise TaskTimeoutError(str(error)) from error
            except Exception as error:
                deliver("error", str(error) or type(error).__name__)
                raise
            deliver("final", said.strip())
            deliver("done", "")

        return self._runner.run(f"Transcribing dictation — {provider.label}", body, key=TASK_KEY)

    def run_live(
        self,
        provider: DictationProvider,
        text: str,
        chunks: "queue.Queue[bytes | None]",
        deliver: Deliver,
    ) -> bool:
        """Open a live session on the runner and feed it what ``chunks`` carries until a
        ``None`` arrives; ``deliver`` hears every ``delta`` and ``final``, then ``done``."""
        listen = provider.listen
        if listen is None:
            return False

        def body() -> None:
            try:
                session = listen(
                    text, lambda said, final: deliver("final" if final else "delta", said)
                )
                while (chunk := chunks.get()) is not None:
                    session.feed(chunk)
                session.finish()
            except Exception as error:
                deliver("error", str(error) or type(error).__name__)
                raise
            deliver("done", "")

        return self._runner.run(f"Live dictation — {provider.label}", body, key=TASK_KEY)


class Dictation(QObject):
    """One microphone's worth of state: press to start, press to stop, hear the words."""

    state_changed = Signal(str)
    heard = Signal(str, bool)  # (text, final): a piece of the utterance, or the whole of it.
    refused = Signal(str)  # Why nothing will happen, or why it stopped.
    _delivered = Signal(int, str, str)  # (generation, kind, text) — worker → GUI thread.

    def __init__(self, service: DictationService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state: State = "idle"
        self._generation = 0
        self._chunks: queue.Queue[bytes | None] | None = None
        self._provider: DictationProvider | None = None
        self._text = ""
        self._recording = Recording(self)
        self._recording.chunk.connect(self._on_chunk)
        self._recording.finished.connect(self._on_recorded)
        self._recording.failed.connect(self._on_failed)
        self._delivered.connect(self._on_delivered)

    @property
    def service(self) -> DictationService:
        return self._service

    def state(self) -> State:
        return self._state

    def bytes_recorded(self) -> int:
        return self._recording.bytes_read()

    def active(self) -> bool:
        return self._state != "idle"

    def toggle(self) -> None:
        """What the button does: start, or stop what is going. Nothing while the words are
        still on their way — pressing twice does not cancel a transcription."""
        if self._state == "idle":
            self.start()
        elif self._state in ("recording", "listening"):
            self.stop()

    def start(self) -> bool:
        if self._state != "idle":
            return False
        status = self._service.status()
        if not status.ready or status.provider is None:
            self.refused.emit(status.message)
            return False
        if self._service.is_busy():
            self.refused.emit(BUSY)
            return False
        self._generation += 1
        generation, delivered = self._generation, self._delivered

        def deliver(kind: str, text: str) -> None:
            # The receiver may have been torn down while the work ran: nothing to tell.
            with contextlib.suppress(RuntimeError):
                delivered.emit(generation, kind, text)

        provider, self._provider, self._text = status.provider, status.provider, status.text
        if provider.live:
            self._chunks = queue.Queue()
            if not self._service.run_live(provider, status.text, self._chunks, deliver):
                self._chunks = None
                self.refused.emit(BUSY)
                return False
        refusal = self._recording.start(list(status.recorder))
        if refusal is not None:
            self._end_live()
            self.refused.emit(refusal)
            return False
        self._deliver = deliver
        self._set_state("listening" if provider.live else "recording")
        return True

    def stop(self) -> None:
        if self._state == "recording":
            self._set_state("transcribing")
            self._recording.stop()
        elif self._state == "listening":
            self._set_state("finishing")
            self._recording.stop()

    def abandon(self) -> None:
        """Forget the clip and drop whatever the run still delivers: the editor moved on."""
        self._generation += 1
        self._recording.discard()
        self._end_live()
        self._set_state("idle")

    # -- the recorder's side ---------------------------------------------------------------

    def _on_chunk(self, data: bytes) -> None:
        if self._chunks is not None and self._state in ("listening", "finishing"):
            self._chunks.put(data)

    def _on_recorded(self, pcm: bytes) -> None:
        if self._state == "finishing":
            self._end_live()  # The session finishes and delivers "done".
            return
        if self._state != "transcribing" or self._provider is None:
            return
        if rms(pcm) < SILENCE_RMS:
            self._set_state("idle")
            self.refused.emit(NOTHING_HEARD)
            return
        wav = wav_bytes(pcm, rate=self._provider.rate)
        if not self._service.run_transcription(self._provider, self._text, wav, self._deliver):
            self._set_state("idle")
            self.refused.emit(BUSY)

    def _on_failed(self, why: str) -> None:
        self._end_live()
        self._set_state("idle")
        self.refused.emit(why)

    def _end_live(self) -> None:
        if self._chunks is not None:
            self._chunks.put(None)
            self._chunks = None

    # -- the worker's side, delivered on the GUI thread ------------------------------------

    def _on_delivered(self, generation: int, kind: str, text: str) -> None:
        if generation != self._generation:
            return  # Abandoned: a transcript for a document this microphone has left.
        if kind == "delta":
            self.heard.emit(text, False)
        elif kind == "final":
            self.heard.emit(text, True)
        elif kind == "done":
            self._set_state("idle")
        elif kind == "error":
            self._recording.discard()
            self._end_live()
            self._set_state("idle")
            self.refused.emit(text)

    def _set_state(self, state: State) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)
