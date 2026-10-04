"""``modules/dictation_whisper``: three whisper commands as providers, over a stand-in CLI."""

import subprocess
import sys

import pytest

from dplanner.core.wav import wav_bytes
from dplanner.modules.dictation_whisper import dictation as whisper

# A CLI stand-in for both shapes: prints the words, or writes them beside the audio.
CLI = r"""
import pathlib, sys, wave
mode, audio = sys.argv[1], pathlib.Path(sys.argv[2])
with wave.open(str(audio)) as clip:
    frames = clip.getnframes()
if mode == "fail":
    sys.stderr.write("failed to load model\n")
    sys.exit(2)
words = f"heard {frames} frames"
if mode == "txt":
    out = pathlib.Path(sys.argv[3])
    (out / f"{audio.stem}.txt").write_text(words + "\n", encoding="utf-8")
else:
    print("whisper_init_from_file: loading model", file=sys.stderr)
    print(words)
"""
WAV = wav_bytes(b"\x00\x10" * 400)


def row(reads="stdout"):
    return whisper.WhisperCli(
        "fake",
        "Fake whisper",
        f"{sys.executable} -c '{CLI}' {reads} {{audio}} {{out}}",
        reads,
        "",
        "",
    )


def test_refusal_names_the_first_token_missing_from_path():
    found = {"whisper-cli": "/usr/bin/whisper-cli"}
    providers = whisper.providers(which=found.get)

    assert [p.id for p in providers] == ["whisper_cpp", "openai_whisper", "whisper_ctranslate2"]
    assert providers[0].refusal(providers[0].default) is None
    assert providers[1].refusal(providers[1].default) == "whisper is not on PATH"
    assert providers[2].refusal("whisper-cli -m other.bin -f {audio}") is None


def test_every_row_is_a_batch_provider_with_a_hint_and_a_place_to_read():
    for provider, spec in zip(whisper.providers(), whisper.WHISPER_CLIS, strict=True):
        assert (provider.caption, provider.default) == ("Command", spec.template)
        assert provider.hint and provider.url.startswith("https://")
        assert not provider.live and provider.transcribe is not None
        assert "{audio}" in spec.template and (spec.reads == "stdout") == (
            "{out}" not in spec.template
        )


def test_a_stdout_row_returns_what_the_cli_printed_and_nothing_from_stderr():
    said = whisper.transcribe_with(row("stdout"), WAV, row("stdout").template)
    assert said == "heard 400 frames"


def test_a_txt_row_reads_the_file_the_cli_wrote_beside_the_audio():
    said = whisper.transcribe_with(row("txt"), WAV, row("txt").template)
    assert said == "heard 400 frames"


def test_the_wav_reaches_the_cli_as_a_real_file_and_the_scratch_is_gone_afterwards(tmp_path):
    seen: list[list[str]] = []

    def run(command, **kwargs):
        seen.append(list(command))
        return subprocess.run(command, **kwargs)

    provider = whisper.command_provider(row("stdout"), run=run)
    assert provider.transcribe is not None
    assert provider.transcribe(WAV, row("stdout").template) == "heard 400 frames"
    audio = next(token for token in seen[0] if token.endswith("clip.wav"))
    assert not __import__("pathlib").Path(audio).exists()


def test_a_cli_that_fails_raises_with_its_own_last_line():
    with pytest.raises(RuntimeError, match="failed to load model"):
        whisper.transcribe_with(
            row("stdout"), WAV, row("stdout").template.replace("stdout", "fail")
        )


def test_a_cli_that_hangs_raises_timeout_expired(monkeypatch):
    monkeypatch.setattr(whisper, "TIMEOUT_S", 0.2)
    template = f"{sys.executable} -c 'import time; time.sleep(5)' {{audio}}"
    with pytest.raises(subprocess.TimeoutExpired):
        whisper.transcribe_with(row("stdout"), WAV, template)


def test_a_placeholder_the_command_does_not_know_reaches_it_literally():
    template = f"{sys.executable} -c 'import sys; print(sys.argv[1])' {{nope}} {{audio}}"
    assert whisper.transcribe_with(row("stdout"), WAV, template) == "{nope}"
