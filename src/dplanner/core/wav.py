"""Raw PCM as a WAV file, and how loud a clip was, with nothing but the standard library.

Two functions, because the dictation stack needs exactly two. A recorder hands over raw
signed 16-bit little-endian samples — the one format every command-line recorder can stream
to a pipe — a transcription provider wants a file with a header, and the control in between
wants to know whether anything was said before it pays a provider to find out. ``audioop``
would have answered the second and left the standard library in 3.13; an ``array`` does.
"""

import io
import math
import sys
import wave
from array import array

RATE = 16000  # What the whisper family was trained on; a provider may ask for another.
CHANNELS = 1
WIDTH = 2  # Bytes per sample: signed 16-bit.

# The most samples ``rms`` reads: a two-minute clip is three million, and the answer is
# whether anybody spoke, not a measurement — a stride keeps it under a tenth of a second.
_RMS_SAMPLES = 200_000


def wav_bytes(
    pcm: bytes, *, rate: int = RATE, channels: int = CHANNELS, width: int = WIDTH
) -> bytes:
    """``pcm`` — interleaved signed little-endian samples of ``width`` bytes — as a WAV.

    A trailing partial frame is dropped: a recorder killed mid-sample leaves one.
    """
    frame = width * channels
    whole = pcm[: len(pcm) - len(pcm) % frame]
    out = io.BytesIO()
    with wave.open(out, "wb") as sink:
        sink.setnchannels(channels)
        sink.setsampwidth(width)
        sink.setframerate(rate)
        sink.writeframes(whole)
    return out.getvalue()


def rms(pcm: bytes) -> float:
    """The clip's level as a share of full scale: 0 for silence, and for no clip at all.

    Signed 16-bit little-endian samples, read at a stride when the clip is long.
    """
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % WIDTH])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    stride = max(1, len(samples) // _RMS_SAMPLES)
    read = samples[::stride]
    return math.sqrt(sum(sample * sample for sample in read) / len(read)) / 32768
