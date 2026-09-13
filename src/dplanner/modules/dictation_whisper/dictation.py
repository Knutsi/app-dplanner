"""The whisper family as dictation providers: a command on this machine, a WAV in, words out.

Three commands, one shape. whisper.cpp's ``whisper-cli`` prints the transcript to stdout when
told to keep quiet about everything else; openai-whisper's ``whisper`` and its CTranslate2
port write a ``.txt`` beside the audio when asked for one. So a row here is a template with
``{audio}`` and, for the second shape, ``{out}``, and a word saying which of the two it
reads. The model is the person's: whisper.cpp wants a downloaded ``ggml`` file after ``-m``,
and the others download a named model on first use — the row's hint says so, behind the
caption's glyph.

**Refusal is the first token.** A command runs on this machine when its program is on PATH;
what the model file is called is not a thing the checklist can know, and a wrong path is
what *Try it* on the settings page is for.
"""

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dplanner.domain.dictation import DictationProvider, Which, command_refusal, split_command

TIMEOUT_S = 300.0  # A local model on a slow machine over a two-minute clip.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class WhisperCli:
    id: str
    label: str
    template: str  # {audio} is the WAV; {out} a directory the transcript is written to.
    reads: Literal["stdout", "txt"]
    hint: str
    url: str


WHISPER_CLIS: tuple[WhisperCli, ...] = (
    WhisperCli(
        "whisper_cpp",
        "whisper.cpp (whisper-cli)",
        "whisper-cli -m ggml-base.en.bin -f {audio} -nt -np",
        "stdout",
        "Put the path of a downloaded ggml model after -m; whisper.cpp's models page "
        "lists them. -nt drops timestamps and -np the chatter, so stdout is the words.",
        "https://github.com/ggml-org/whisper.cpp",
    ),
    WhisperCli(
        "openai_whisper",
        "openai-whisper (whisper)",
        "whisper {audio} --model base --output_format txt --output_dir {out}",
        "txt",
        "The model after --model is downloaded on first use; base.en is quick, small is "
        "better. Install with: uv tool install openai-whisper",
        "https://github.com/openai/whisper",
    ),
    WhisperCli(
        "whisper_ctranslate2",
        "whisper-ctranslate2",
        "whisper-ctranslate2 {audio} --model base --output_format txt --output_dir {out}",
        "txt",
        "The faster-whisper port with openai-whisper's command line. Install with: "
        "uv tool install whisper-ctranslate2",
        "https://github.com/Softcatala/whisper-ctranslate2",
    ),
)


def transcribe_with(
    row: WhisperCli, wav: bytes, template: str, *, run: Runner = subprocess.run
) -> str:
    """Write the clip beside a scratch directory, run the command over it, read the words.

    BLOCKING: a worker thread's. Raises ``subprocess.TimeoutExpired`` past ``TIMEOUT_S``
    and ``RuntimeError`` with the command's own stderr when it failed.
    """
    with tempfile.TemporaryDirectory(prefix="dplanner-dictation-") as scratch:
        audio = Path(scratch) / "clip.wav"
        audio.write_bytes(wav)
        out = Path(scratch) / "out"
        out.mkdir()
        command = split_command(template, audio=str(audio), out=str(out))
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW  # No console flashing up behind the editor.
        result = run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
            creationflags=flags,
        )
        if result.returncode != 0:
            why = (result.stderr or result.stdout).strip().splitlines()
            raise RuntimeError(why[-1] if why else f"{command[0]} exited with {result.returncode}")
        if row.reads == "txt":
            written = out / f"{audio.stem}.txt"
            return written.read_text(encoding="utf-8").strip() if written.exists() else ""
        return result.stdout.strip()


def command_provider(
    row: WhisperCli, *, which: Which = shutil.which, run: Runner = subprocess.run
) -> DictationProvider:
    return DictationProvider(
        id=row.id,
        label=row.label,
        caption="Command",
        default=row.template,
        refusal=lambda text: command_refusal(text, which),
        transcribe=lambda wav, text: transcribe_with(row, wav, text, run=run),
        hint=row.hint,
        url=row.url,
    )


def providers(
    *, which: Which = shutil.which, run: Runner = subprocess.run
) -> tuple[DictationProvider, ...]:
    """The three rows as providers, in the order the settings page lists them."""
    return tuple(command_provider(row, which=which, run=run) for row in WHISPER_CLIS)
