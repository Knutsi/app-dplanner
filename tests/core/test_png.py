"""The PNG encoder: a valid, deterministic file from raw RGB rows."""

import struct
import zlib

import pytest

from dplanner.core.png import encode_rgb

RED, GREEN = b"\xff\x00\x00", b"\x00\xff\x00"


def test_a_2x2_image_round_trips_through_the_container():
    pixels = RED + GREEN + GREEN + RED
    data = encode_rgb(2, 2, 6, pixels)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

    # IHDR: right after the signature; says 2x2, 8-bit, colour type 2 (RGB).
    length, kind = struct.unpack(">I4s", data[8:16])
    assert kind == b"IHDR"
    width, height, depth, colour = struct.unpack(">IIBB", data[16 : 16 + 10])
    assert (width, height, depth, colour) == (2, 2, 8, 2)

    # IDAT decompresses to the scanlines, each prefixed with filter 0.
    idat_start = 16 + length + 4
    idat_length, idat_kind = struct.unpack(">I4s", data[idat_start : idat_start + 8])
    assert idat_kind == b"IDAT"
    raw = zlib.decompress(data[idat_start + 8 : idat_start + 8 + idat_length])
    assert raw == b"\x00" + RED + GREEN + b"\x00" + GREEN + RED

    # Every chunk's CRC holds, and the file ends in IEND.
    at = 8
    kinds = []
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        payload = data[at + 8 : at + 8 + length]
        (crc,) = struct.unpack(">I", data[at + 8 + length : at + 12 + length])
        assert crc == zlib.crc32(kind + payload)
        kinds.append(kind)
        at += 12 + length
    assert kinds == [b"IHDR", b"IDAT", b"IEND"]


def test_stride_padding_is_dropped():
    data = encode_rgb(1, 2, 4, RED + b"\x00" + GREEN + b"\x00")
    idat = data[8 + 12 + 13 :]  # signature + IHDR chunk
    length = struct.unpack(">I", idat[:4])[0]
    assert zlib.decompress(idat[8 : 8 + length]) == b"\x00" + RED + b"\x00" + GREEN


def test_identical_pixels_give_identical_bytes():
    pixels = RED + GREEN
    assert encode_rgb(2, 1, 6, pixels) == encode_rgb(2, 1, 6, pixels)


def test_a_short_buffer_is_refused():
    with pytest.raises(ValueError, match="smaller than the dimensions"):
        encode_rgb(2, 2, 6, RED)
    with pytest.raises(ValueError, match="at least one pixel"):
        encode_rgb(0, 0, 0, b"")
