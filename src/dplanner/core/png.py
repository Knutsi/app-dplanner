"""Encoding an RGB buffer as a PNG, with nothing but the standard library.

One function, because one caller needs it: the spec module renders PDF pages into image
assets, and pulling in an imaging library — or Qt, which the CLI must never load — for
IHDR-plus-IDAT would be the heavier dependency. Deterministic on purpose: a fixed zlib
level and no ancillary chunks, so identical pixels give identical bytes and content
addressing can see that a re-render changed nothing.
"""

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COMPRESSION_LEVEL = 9  # Fixed: determinism is part of the contract, not just size.


def encode_rgb(width: int, height: int, stride: int, pixels: bytes) -> bytes:
    """``pixels`` as 8-bit RGB rows, each ``stride`` bytes long, top to bottom."""
    row_bytes = width * 3
    if width <= 0 or height <= 0:
        raise ValueError("an image needs at least one pixel")
    if stride < row_bytes or len(pixels) < stride * height:
        raise ValueError("buffer is smaller than the dimensions promise")
    raw = b"".join(
        b"\x00" + pixels[row * stride : row * stride + row_bytes] for row in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    return b"".join(
        (
            _SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(raw, _COMPRESSION_LEVEL)),
            _chunk(b"IEND", b""),
        )
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )
