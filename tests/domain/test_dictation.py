"""``domain/dictation.py``: the provider record, the recorder table and the helpers every
dictation surface reads."""

import pytest

from dplanner.domain import dictation
from dplanner.domain.dictation import DictationProvider, Recorder


class _Session:
    def feed(self, pcm: bytes) -> None:
        pass

    def finish(self) -> None:
        pass


def provider(
    provider_id="one", *, refusal=None, live=False, setup_action="", default="run {audio}"
):
    return DictationProvider(
        id=provider_id,
        label=provider_id.title(),
        caption="Command",
        default=default,
        refusal=lambda _text: refusal,
        transcribe=None if live else (lambda _wav, _text: "said"),
        listen=(lambda _text, _deltas: _Session()) if live else None,
        setup_action=setup_action,
    )


def test_capabilities_are_derived_from_the_record():
    batch, live = provider(), provider(live=True)

    assert (batch.live, live.live) == (False, True)
    assert batch.capabilities() == ("transcribed when you stop",)
    assert live.capabilities() == ("words land as you speak",)
    assert not batch.needs_setup and provider(setup_action="openai.key").needs_setup


def test_recorders_for_a_platform_are_only_that_platforms_rows():
    linux = dictation.recorders_for("linux")
    assert [recorder.id for recorder in linux][:2] == ["pw-record", "parecord"]
    assert all(recorder.platform == "linux" for recorder in linux)
    assert [recorder.id for recorder in dictation.recorders_for("win32")] == ["ffmpeg-win"]
    assert [recorder.id for recorder in dictation.recorders_for("darwin")] == [
        "sox-mac",
        "ffmpeg-mac",
    ]


def test_every_row_captures_mono_at_the_providers_rate_to_stdout():
    for recorder in dictation.RECORDERS:
        assert "{rate}" in recorder.command
        assert recorder.command.split()[0] == recorder.probe
        tokens = dictation.split_command(recorder.command, rate="24000")
        assert any("24000" in token for token in tokens)


def test_first_installed_is_the_first_row_whose_probe_is_on_path():
    found = {"arecord": "/usr/bin/arecord", "ffmpeg": "/usr/bin/ffmpeg"}
    rows = dictation.recorders_for("linux")

    picked = dictation.first_installed(rows, which=found.get)

    assert picked is not None and picked.id == "arecord"
    assert dictation.first_installed(rows, which=lambda _name: None) is None


def test_recorder_for_command_reads_a_stored_text_back_as_its_row():
    rows = dictation.recorders_for("linux")
    assert dictation.recorder_for_command(rows, f" {rows[1].command} ") is rows[1]
    assert dictation.recorder_for_command(rows, "my-recorder --raw") is None


def test_first_available_picks_the_first_provider_that_does_not_refuse():
    providers = (provider("a", refusal="not on PATH"), provider("b"), provider("c"))

    assert dictation.first_available(providers) == (providers[1], "run {audio}")
    assert dictation.first_available((provider("a", refusal="no"),)) is None


def test_first_available_runs_a_stored_text_over_the_default():
    providers = (provider("b", default="default"),)

    assert dictation.first_available(providers, {"b": "typed"}) == (providers[0], "typed")
    assert dictation.first_available(providers, {"b": ""}) == (providers[0], "default")


def test_provider_by_id():
    providers = (provider("a"), provider("b"))
    assert dictation.provider_by_id(providers, "b") is providers[1]
    assert dictation.provider_by_id(providers, "z") is None


def test_split_command_substitutes_per_token_so_a_windows_path_never_meets_shlex():
    path = r"C:\Users\Knut Å\clip.wav"

    tokens = dictation.split_command('whisper-cli -f {audio} -m "a b.bin"', audio=path)

    assert tokens == ["whisper-cli", "-f", path, "-m", "a b.bin"]


def test_split_command_leaves_a_brace_that_is_the_commands_own_alone():
    tokens = dictation.split_command("run --prompt '{x} {audio}' {nope}", audio="a.wav")
    assert tokens == ["run", "--prompt", "{x} a.wav", "{nope}"]
    with pytest.raises(ValueError):
        dictation.split_command('"unterminated', audio="a.wav")


def test_command_refusal_names_what_is_wrong():
    found = {"whisper-cli": "/usr/bin/whisper-cli"}

    assert dictation.command_refusal("whisper-cli -m x", which=found.get) is None
    assert dictation.command_refusal("whisper -m x", which=found.get) == "whisper is not on PATH"
    assert dictation.command_refusal("   ", which=found.get) == "no command"
    unreadable = dictation.command_refusal('"unterminated', which=found.get)
    assert unreadable is not None and unreadable.startswith("cannot read")


def test_a_recorder_row_is_a_plain_record():
    row = Recorder("x", "X", "linux", "x --rate {rate}", "x")
    assert (row.hint, row.probe) == ("", "x")
