"""The vocabulary a source kind and the spec module exchange.

Only the pieces that carry a rule are tested here: the raster sniffer, which is one table
because two kinds sniffing differently would name one picture two ways.
"""

from dplanner.domain.document_source import Freshness, Snapshot, raster_suffix

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def test_sniffing_knows_the_four_raster_formats():
    assert raster_suffix(PNG) == ".png"
    assert raster_suffix(b"\xff\xd8\xff\xe0") == ".jpg"
    assert raster_suffix(b"GIF87a...") == ".gif"
    assert raster_suffix(b"GIF89a...") == ".gif"
    assert raster_suffix(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"


def test_an_svg_is_not_a_raster_image():
    # XML that can carry script; nothing a spec needs is lost by leaving it out.
    assert raster_suffix(b"<svg/>") is None
    assert raster_suffix(b"") is None


def test_a_snapshot_orders_its_fetched_keys_before_its_kept_ones_by_default():
    assert Snapshot(documents=(), kept=("a", "b")).keys() == ("a", "b")
    assert Snapshot(documents=(), kept=("b",), order=("a", "b")).keys() == ("a", "b")


def test_freshness_is_stale_when_anything_moved():
    assert not Freshness().stale
    assert Freshness(changed=("a",)).stale
    assert Freshness(added=("a",)).stale
    assert Freshness(removed=("a",)).stale
