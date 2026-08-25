"""The workspace-format chain: what it accepts, what it refuses, and in what order."""

from pathlib import Path

import pytest

from dplanner.core.formats import FormatHistory, Migration, UnsupportedFormatError


def history(*migrations: Migration[object, object]) -> FormatHistory[object, object]:
    """A chain over throwaway node/root types — the engine does not care which."""
    return FormatHistory(migrations)


def test_an_empty_chain_is_version_one():
    assert history().current_version == 1


def test_the_version_is_derived_from_the_chain():
    chain = history(Migration(version=2, note="a"), Migration(version=3, note="b"))
    assert chain.current_version == 3


def test_migrations_must_be_ordered_and_unique():
    with pytest.raises(ValueError, match="ordered"):
        history(Migration(version=3, note="b"), Migration(version=2, note="a"))
    with pytest.raises(ValueError, match="ordered"):
        history(Migration(version=2, note="a"), Migration(version=2, note="a"))


def test_the_first_migration_is_version_two():
    """Version 1 is the beginning; there is nothing for a migration to that to do."""
    with pytest.raises(ValueError, match="version 2"):
        history(Migration(version=1, note="nope"))


def test_pending_returns_only_what_is_newer():
    chain = history(Migration(version=2, note="a"), Migration(version=3, note="b"))
    assert [m.version for m in chain.pending(1)] == [2, 3]
    assert [m.version for m in chain.pending(2)] == [3]
    assert chain.pending(3) == ()


def test_a_newer_format_is_refused_and_says_why():
    with pytest.raises(UnsupportedFormatError) as caught:
        history().read_version({"format": 4}, Path("/tmp/ws"))
    assert caught.value.is_newer


def test_a_missing_format_is_refused_but_not_as_newer():
    with pytest.raises(UnsupportedFormatError) as caught:
        history().read_version({}, Path("/tmp/ws"))
    assert not caught.value.is_newer
