"""``core/wav.py``: the header a recorder's raw samples get, and how loud they were."""

import io
import struct
import wave

from dplanner.core import wav


def _tone(amplitude: int, count: int) -> bytes:
    """A square wave at ``amplitude``: every sample is plus or minus it."""
    return b"".join(struct.pack("<h", amplitude if i % 2 else -amplitude) for i in range(count))


def test_wav_bytes_wraps_pcm_in_the_header_the_recorder_was_asked_for():
    pcm = _tone(1000, 400)

    made = wav.wav_bytes(pcm, rate=24000)

    with wave.open(io.BytesIO(made)) as read:
        assert (read.getnchannels(), read.getsampwidth(), read.getframerate()) == (1, 2, 24000)
        assert read.readframes(read.getnframes()) == pcm


def test_wav_bytes_defaults_to_the_whisper_rate_and_drops_a_partial_frame():
    pcm = _tone(1000, 10) + b"\x7f"  # A recorder killed mid-sample leaves an odd byte.

    with wave.open(io.BytesIO(wav.wav_bytes(pcm))) as read:
        assert read.getframerate() == wav.RATE
        assert read.getnframes() == 10


def test_rms_is_zero_for_silence_and_for_nothing_at_all():
    assert wav.rms(b"") == 0.0
    assert wav.rms(b"\x00" * 1000) == 0.0


def test_rms_reads_full_scale_as_one_and_a_quiet_clip_as_its_share():
    assert wav.rms(_tone(32767, 1000)) > 0.999
    assert abs(wav.rms(_tone(3277, 1000)) - 0.1) < 0.001


def test_rms_strides_a_long_clip_and_still_answers_its_level():
    long = _tone(16384, 2 * wav._RMS_SAMPLES + 7)

    assert abs(wav.rms(long) - 0.5) < 0.01


def test_rms_drops_an_odd_trailing_byte_rather_than_raising():
    assert wav.rms(_tone(1000, 4) + b"\x01") == wav.rms(_tone(1000, 4))
