"""``write_atomic`` under two writers: neither can tear the file or strand the other."""

import os

import pytest

from dplanner.core.fsio import write_atomic


def test_two_writers_interleaving_on_one_path_both_land(tmp_path, monkeypatch):
    """The review's probe: writer A pauses before its rename while writer B writes the same
    path from start to finish. With one shared temporary name, A's rename found its file
    gone (B had renamed it) — each writer must have a temporary of its own."""
    path = tmp_path / "library.json"
    replace = os.replace
    interleaved: list[str] = []

    def a_pauses_while_b_writes(src: str, dst: str) -> None:
        if not interleaved:
            interleaved.append("B")
            write_atomic(path, "B\n")
        replace(src, dst)

    monkeypatch.setattr(os, "replace", a_pauses_while_b_writes)

    write_atomic(path, "A\n")

    assert interleaved == ["B"]
    assert path.read_text() == "A\n"  # The last rename wins, whole.
    assert [entry.name for entry in tmp_path.iterdir()] == [path.name]


def test_a_failed_write_leaves_no_temporary_behind(tmp_path, monkeypatch):
    path = tmp_path / "library.json"

    def refuses(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuses)

    with pytest.raises(OSError):
        write_atomic(path, "A\n")

    assert list(tmp_path.iterdir()) == []
