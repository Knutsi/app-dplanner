"""A minimal observer mechanism for the Qt-free core.

The core cannot use Qt signals without dragging Qt into every model test, and it needs far
less than Qt offers: no threads, no queued connections, no sender objects. This is the
smallest thing that works: a list of callables, called in connection order.

Emission is where a model change turns into every view's work, synchronously, so it is
also where that work is measured: each slot is timed, and one that takes
``telemetry.SLOW_MS`` or longer is journaled by name — the one cross-cutting place the
cost of a change can be read off, per listener, without any view learning to time itself.
"""

import logging
from collections.abc import Callable
from time import perf_counter

from dplanner.core.telemetry import current, describe_slot

logger = logging.getLogger(__name__)


class Signal[*Ts]:
    """A synchronous multicast callable, typed by its argument tuple.

    ``connect`` returns an unsubscribe callable so listeners with short lifetimes (a view
    binding, a test) can detach without keeping a reference to the slot they registered.
    ``name`` is for the journal — which signal a slow slot was heard through; the model's
    fan-out signals carry one, an anonymous one reads as "".
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._slots: list[Callable[[*Ts], None]] = []

    def connect(self, slot: Callable[[*Ts], None]) -> Callable[[], None]:
        """Register ``slot`` and return an idempotent unsubscribe callable."""
        self._slots.append(slot)
        # The flag makes the unsubscriber idempotent even if the same function object was
        # connected twice: each connect() owns exactly one registration.
        unsubscribed = False

        def unsubscribe() -> None:
            nonlocal unsubscribed
            if not unsubscribed:
                unsubscribed = True
                self._slots.remove(slot)

        return unsubscribe

    def disconnect(self, slot: Callable[[*Ts], None]) -> None:
        """Remove one registration of ``slot``; raises ``ValueError`` if it is not connected."""
        self._slots.remove(slot)

    def emit(self, *args: *Ts) -> None:
        """Call every connected slot with ``args``, in connection order.

        Iterates a copy so a slot may connect or disconnect during emission without
        corrupting the walk. A slot that raises is logged and skipped: a broken listener
        must not abort the model mutation that triggered the signal, nor starve the
        listeners queued behind it. (The log record is what journals it as a failure.)
        """
        telemetry = current()
        for slot in list(self._slots):
            started = perf_counter()
            try:
                slot(*args)
            except Exception:
                logger.exception("signal slot %r failed", slot)
            finally:
                elapsed = (perf_counter() - started) * 1000.0
                if elapsed >= telemetry.slow_ms:
                    telemetry.record(
                        "slot", describe_slot(slot), duration_ms=elapsed, signal=self.name
                    )
