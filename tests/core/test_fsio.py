"""``write_atomic`` under two writers: neither can tear the file or strand the other."""

import errno
import os
import sys
import time

import pytest

from dplanner.core.fsio import os_lock, write_atomic


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


class _FakeMsvcrt:
    """``msvcrt.locking`` refusing with what Windows raises while another process holds the
    byte, ``held`` times over, then granting."""

    LK_LOCK, LK_NBLCK = 1, 2

    def __init__(self, held: int, error: int = errno.EACCES) -> None:
        self.held, self.error = held, error
        self.modes: list[int] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.modes.append(mode)
        if self.held:
            self.held -= 1
            raise OSError(self.error, "held")


def _as_windows(monkeypatch, fake: _FakeMsvcrt) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def test_a_windows_wait_lock_waits_past_any_count_of_refusals(tmp_path, monkeypatch):
    """LK_LOCK gives up after ten seconds, and a fetch can hold the sync lock longer: a
    waiting Save raised instead of waiting. Waiting retries the non-blocking lock until the
    holder lets go."""
    fake = _FakeMsvcrt(held=50)
    slept = _as_windows(monkeypatch, fake)

    with os_lock(tmp_path / "x.lock", wait=True):
        pass

    assert fake.modes == [fake.LK_NBLCK] * 51
    assert len(slept) == 50


def test_a_windows_lock_without_wait_refuses_at_once(tmp_path, monkeypatch):
    fake = _FakeMsvcrt(held=1)
    slept = _as_windows(monkeypatch, fake)

    with pytest.raises(BlockingIOError), os_lock(tmp_path / "x.lock", wait=False):
        pass

    assert fake.modes == [fake.LK_NBLCK]
    assert slept == []


def test_a_windows_lock_propagates_an_error_that_is_not_contention(tmp_path, monkeypatch):
    fake = _FakeMsvcrt(held=1, error=errno.EBADF)
    _as_windows(monkeypatch, fake)

    with pytest.raises(OSError) as raised, os_lock(tmp_path / "x.lock", wait=True):
        pass

    assert not isinstance(raised.value, BlockingIOError)
    assert raised.value.errno == errno.EBADF
