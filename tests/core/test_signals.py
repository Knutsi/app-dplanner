"""The observer primitive: ordering, unsubscribing, and isolation from broken listeners."""

import pytest

from dplanner.core.signals import Signal
from dplanner.core.telemetry import Telemetry, install


def test_slots_run_in_connection_order():
    seen = []
    signal: Signal[int] = Signal()
    signal.connect(lambda value: seen.append(("first", value)))
    signal.connect(lambda value: seen.append(("second", value)))
    signal.emit(1)
    assert seen == [("first", 1), ("second", 1)]


def test_unsubscribe_is_idempotent():
    seen = []
    signal: Signal[()] = Signal()
    unsubscribe = signal.connect(lambda: seen.append(1))
    unsubscribe()
    unsubscribe()  # A second call must not remove someone else's registration.
    signal.connect(lambda: seen.append(2))
    signal.emit()
    assert seen == [2]


def test_a_slot_may_disconnect_during_emission():
    seen = []
    signal: Signal[()] = Signal()

    def once():
        seen.append("once")
        unsubscribe()

    unsubscribe = signal.connect(once)
    signal.connect(lambda: seen.append("after"))
    signal.emit()
    signal.emit()
    assert seen == ["once", "after", "after"]


def test_a_raising_slot_does_not_starve_the_others(caplog):
    """A broken listener must not abort the mutation that triggered the signal."""
    seen = []
    signal: Signal[()] = Signal()

    def raises() -> None:
        raise RuntimeError("this listener is broken")

    signal.connect(raises)
    signal.connect(lambda: seen.append("still ran"))
    signal.emit()
    assert seen == ["still ran"]


# -- what emission journals ----------------------------------------------------------------------


@pytest.fixture
def journal():
    """A throwaway process journal that keeps every slot, however quick."""
    made = Telemetry(slow_ms=0.0)
    previous = install(made)
    try:
        yield made
    finally:
        install(previous)


class _View:
    def refresh(self, _value: int) -> None:
        pass


def test_a_slow_slot_is_journaled_by_name_and_signal(journal):
    signal: Signal[int] = Signal("field_changed")
    signal.connect(_View().refresh)
    signal.emit(1)
    (span,) = journal.recent()
    assert span.kind == "slot" and span.detail == {"signal": "field_changed"}
    assert span.name.startswith("_View.refresh (test_signals.py:")


def test_a_raising_slot_is_journaled_as_a_failure(journal):
    signal: Signal[()] = Signal()

    def raises() -> None:
        raise RuntimeError("this listener is broken")

    signal.connect(raises)
    signal.emit()
    failure = next(span for span in journal.recent() if span.kind == "failure")
    assert failure.error_type == "RuntimeError"
    assert "this listener is broken" in (failure.traceback or "")
