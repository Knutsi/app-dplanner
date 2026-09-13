"""What a dictation engine is to DPlanner: the **provider** contract a module fills, and the
**recorder** table beside it.

A microphone button on a prose editor does two things: it records what is said, and it has
the words written down. The second is a provider's — a whisper command on this machine, a
transcription API behind a key — and each provider module writes its facts down once in a
:class:`DictationProvider`, from its Qt-free half, the way an agent CLI is an
:class:`~dplanner.domain.agents.AgentHarness`. The composition root assembles the tuple; the
service, the settings page and the checklist read it. A fourth engine is a fourth module and
no ``if`` anywhere.

**Capabilities are derived from the record, never declared beside it.** A provider that
carries ``listen`` is live — words land as they are spoken — and one that carries only
``transcribe`` is batch, its transcript arriving once the recording stops. One that names a
``setup_action`` can be set up from where its refusal is shown.

**Capture is a peer process.** PySide6-Essentials ships no QtMultimedia, so the microphone is
read by whichever recorder this machine has — ``pw-record``, ``parecord``, ``arecord``,
``ffmpeg``, ``sox`` — streaming raw signed 16-bit mono samples to a pipe. A recorder is a row
here, with a probe saying whether it is installed, like a terminal in the launcher's table;
*Automatic* is the first installed row for this platform, and a person who knows better
types a command of their own. The rate is the provider's, because the whisper family wants
16 kHz and a realtime API wants 24 kHz: the row carries ``{rate}`` and the service fills it.
"""

import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from dplanner.core.wav import RATE

# A delta sink: the text and whether it is an utterance's completed transcript, which
# replaces the deltas that led to it, or one more piece of the utterance still being said.
type Deltas = Callable[[str, bool], None]
type Which = Callable[[str], str | None]


class LiveSession(Protocol):
    """One live transcription, fed audio as it is captured. Runs on a worker thread."""

    def feed(self, pcm: bytes) -> None:
        """Send one chunk of signed 16-bit mono samples at the provider's rate."""
        ...

    def finish(self) -> None:
        """Flush what is buffered, wait a bounded time for the last transcript, close."""
        ...


@dataclass(frozen=True)
class DictationProvider:
    id: str  # "whisper_cpp" — what the settings store.
    label: str  # "whisper.cpp (whisper-cli)" — what a dropdown says.
    caption: str  # What its one editable text is: "Command" or "Model".
    default: str  # What that text is pre-filled with.
    # Why this provider cannot run with that text — not on PATH, no key — or None.
    refusal: Callable[[str], str | None]
    # Batch: a WAV and the text, the transcript back. BLOCKING; a worker thread's.
    transcribe: Callable[[bytes, str], str] | None = None
    # Live: the text and a delta sink, a session back. The session runs on a worker.
    listen: Callable[[str, Deltas], LiveSession] | None = None
    rate: int = RATE  # The sample rate it wants the recorder to capture at.
    hint: str = ""  # One sentence behind the caption's info glyph: a model file, a key.
    url: str = ""  # Where to read about installing it.
    setup_action: str = ""  # An action that mends the refusal — adding a key, say.

    @property
    def live(self) -> bool:
        return self.listen is not None

    @property
    def needs_setup(self) -> bool:
        return bool(self.setup_action)

    def capabilities(self) -> tuple[str, ...]:
        """The provider's abilities in words, for a settings page or a listing."""
        return ("words land as you speak",) if self.live else ("transcribed when you stop",)


@dataclass(frozen=True)
class Recorder:
    id: str
    label: str
    platform: str  # A ``sys.platform`` prefix: one row per platform, like a terminal.
    command: str  # ``{rate}`` becomes the provider's rate; the samples go to stdout.
    probe: str  # The binary asked of PATH.
    hint: str = ""  # What a person may have to change: a device name.


def _ffmpeg(source: str) -> str:
    # ``-flush_packets 1``: raw output has no trailer, and a recorder stopped by a kill —
    # the only stop Windows has for a console process — keeps everything it flushed.
    return f"ffmpeg -loglevel error {source} -ac 1 -ar {{rate}} -f s16le -flush_packets 1 -"


_SOX = "sox -q -d -r {rate} -c 1 -b 16 -e signed-integer -t raw -"

RECORDERS: tuple[Recorder, ...] = (
    Recorder(
        "pw-record",
        "PipeWire (pw-record)",
        "linux",
        "pw-record --raw --rate {rate} --channels 1 --format s16 -",
        "pw-record",
    ),
    Recorder(
        "parecord",
        "PulseAudio (parecord)",
        "linux",
        "parecord --raw --format=s16le --rate={rate} --channels=1",
        "parecord",
    ),
    Recorder(
        "arecord",
        "ALSA (arecord)",
        "linux",
        "arecord -q -t raw -f S16_LE -r {rate} -c 1",
        "arecord",
    ),
    Recorder("ffmpeg", "ffmpeg (PulseAudio)", "linux", _ffmpeg("-f pulse -i default"), "ffmpeg"),
    Recorder("sox", "sox", "linux", _SOX, "sox"),
    Recorder("sox-mac", "sox", "darwin", _SOX, "sox"),
    Recorder(
        "ffmpeg-mac", "ffmpeg (AVFoundation)", "darwin", _ffmpeg("-f avfoundation -i :0"), "ffmpeg"
    ),
    Recorder(
        "ffmpeg-win",
        "ffmpeg (DirectShow)",
        "win32",
        _ffmpeg('-f dshow -i audio="Microphone"'),
        "ffmpeg",
        hint="The device is named as DirectShow lists it: "
        "ffmpeg -list_devices true -f dshow -i dummy",
    ),
)


def recorders_for(
    platform: str = sys.platform, recorders: Sequence[Recorder] = RECORDERS
) -> tuple[Recorder, ...]:
    return tuple(recorder for recorder in recorders if platform.startswith(recorder.platform))


def is_installed(recorder: Recorder, which: Which = shutil.which) -> bool:
    return which(recorder.probe) is not None


def first_installed(recorders: Sequence[Recorder], which: Which = shutil.which) -> Recorder | None:
    """What *Automatic* means: the first row this machine has."""
    return next((recorder for recorder in recorders if is_installed(recorder, which)), None)


def recorder_for_command(recorders: Sequence[Recorder], text: str) -> Recorder | None:
    """The row a stored command text means, or None for a command somebody typed."""
    stripped = text.strip()
    return next((recorder for recorder in recorders if recorder.command == stripped), None)


def provider_by_id(
    providers: Sequence[DictationProvider], provider_id: str
) -> DictationProvider | None:
    return next((provider for provider in providers if provider.id == provider_id), None)


def first_available(
    providers: Sequence[DictationProvider], texts: Mapping[str, str] = {}
) -> tuple[DictationProvider, str] | None:
    """The first provider that does not refuse, with the text it would run — a stored
    one under its id, else its default. What a fresh profile dictates with."""
    for provider in providers:
        text = texts.get(provider.id) or provider.default
        if provider.refusal(text) is None:
            return provider, text
    return None


def split_command(template: str, **values: str) -> list[str]:
    """Split like a shell, then substitute per token — a Windows path never meets shlex.

    Only the named placeholders are touched, by plain replacement: a brace that is the
    command's own is left alone. Raises ``ValueError`` for a template that cannot be split.
    """
    tokens = []
    for token in shlex.split(template):
        for name, value in values.items():
            token = token.replace("{" + name + "}", value)
        tokens.append(token)
    return tokens


def command_refusal(text: str, which: Which = shutil.which) -> str | None:
    """Why a command text cannot run here: empty, unsplittable, or its program not on PATH."""
    try:
        tokens = shlex.split(text)
    except ValueError as error:
        return f"cannot read the command: {error}"
    if not tokens:
        return "no command"
    if which(tokens[0]) is None:
        return f"{tokens[0]} is not on PATH"
    return None
