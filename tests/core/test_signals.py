"""The observer primitive: ordering, unsubscribing, and isolation from broken listeners."""

from dplanner.core.signals import Signal


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
