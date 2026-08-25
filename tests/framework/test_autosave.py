"""Autosave: debounce, batching, pausing, and what it does not know."""

import pytest

from dplanner.core.signals import Signal
from dplanner.framework.autosave import AutosaveService


class RecordingPersister:
    def __init__(self):
        self.batches = []

    def flush(self, marks):
        self.batches.append(set(marks))


@pytest.fixture
def parts(app):
    dirty: Signal[str, str] = Signal()
    persister = RecordingPersister()
    service = AutosaveService(dirty, persister)
    yield dirty, persister, service
    service.stop()


def test_nothing_is_written_before_the_debounce(parts):
    dirty, persister, _service = parts
    dirty.emit("a", "text")
    assert persister.batches == []


def test_a_flush_delivers_the_whole_batch_at_once(parts):
    """Ordering between aspects is the store's business, so it gets the set, not a stream."""
    dirty, persister, service = parts
    dirty.emit("a", "text")
    dirty.emit("a", "meta")
    dirty.emit("b", "text")
    service.flush_now()
    assert persister.batches == [{("a", "text"), ("a", "meta"), ("b", "text")}]


def test_the_same_mark_twice_is_written_once(parts):
    dirty, persister, service = parts
    dirty.emit("a", "text")
    dirty.emit("a", "text")
    service.flush_now()
    assert persister.batches == [{("a", "text")}]


def test_a_flush_with_nothing_pending_does_nothing(parts):
    _dirty, persister, service = parts
    service.flush_now()
    assert persister.batches == []


def test_pausing_holds_writes_back(parts):
    dirty, persister, service = parts
    service.pause()
    dirty.emit("a", "text")
    service.flush_now()
    assert persister.batches == []
    service.resume()
    service.flush_now()
    assert persister.batches == [{("a", "text")}]


def test_pauses_nest(parts):
    """A checkout inside another operation must not be un-paused by the inner one."""
    dirty, persister, service = parts
    service.pause()
    service.pause()
    dirty.emit("a", "text")
    service.resume()
    service.flush_now()
    assert persister.batches == []
    service.resume()
    service.flush_now()
    assert persister.batches == [{("a", "text")}]


def test_stopping_detaches_for_good(parts):
    dirty, persister, service = parts
    service.stop()
    dirty.emit("a", "text")
    service.flush_now()
    assert persister.batches == []


def test_flushing_announces_itself(parts):
    dirty, _persister, service = parts
    seen = []
    service.flushed.connect(lambda: seen.append(1))
    dirty.emit("a", "text")
    service.flush_now()
    assert seen == [1]
