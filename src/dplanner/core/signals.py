"""A minimal observer mechanism for the Qt-free core.

The core cannot use Qt signals without dragging Qt into every model test, and it needs far
less than Qt offers: no threads, no queued connections, no sender objects. This is the
smallest thing that works: a list of callables, called in connection order.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class Signal[*Ts]:
    """A synchronous multicast callable, typed by its argument tuple.

    ``connect`` returns an unsubscribe callable so listeners with short lifetimes (a view
    binding, a test) can detach without keeping a reference to the slot they registered.
    """

    def __init__(self) -> None:
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
        listeners queued behind it.
        """
        for slot in list(self._slots):
            try:
                slot(*args)
            except Exception:
                logger.exception("signal slot %r failed", slot)
