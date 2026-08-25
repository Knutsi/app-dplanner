"""Debounced persistence: memory is authoritative, disk follows.

The repository says what became dirty; this service decides *when* to write it and hands
the whole batch to :meth:`~dplanner.core.repository.Persister.flush`. It knows nothing about
what an aspect means — "text", "structure", "dependencies" are your store's words — which
is the difference between an autosave that serves one model and one that serves any.

There is no "Save file" action anywhere in an application built this way. Files are always
current within the debounce; what a user calls **Save** is recording a version, and that
only exists when the storage provider has a history.

Two behaviours are worth keeping when you change this file:

**Restart the timer on every mark.** The flush happens after a quiet spell, not on a fixed
cadence — so a burst of typing costs one write, and a pause costs nothing.

**``pause()`` nests.** A branch switch rewrites files under the running application; a
flush racing it would write a stale model over freshly checked-out content. The counter is
what lets the reload path leave autosave paused and simply discard the whole build.

**A refused write keeps its marks and stops trying.** A store may decline to flush — the
usual reason is that something else wrote to the same folder — and the wrong answers are
both obvious: dropping the marks loses the user's edits, and retrying every 1.5 seconds
turns one problem into an endless one. So the batch goes back, autosave pauses itself, and
``failed`` says so. Whoever is listening decides; ``resume()`` is how they say to try again.
"""

from PySide6.QtCore import QTimer

from dplanner.core.repository import DirtyMark, Persister
from dplanner.core.signals import Signal

FLUSH_DELAY_MS = 1500


class AutosaveService:
    """Batches ``dirty`` marks and flushes them after a quiet spell."""

    def __init__(self, dirty: Signal[str, str], persister: Persister) -> None:
        self._persister = persister
        self._dirty: set[DirtyMark] = set()
        self._paused = 0
        self.flushed: Signal[()] = Signal()
        self.failed: Signal[Exception] = Signal()

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(FLUSH_DELAY_MS)
        self._timer.timeout.connect(self.flush_now)
        self._unsubscribe = dirty.connect(self.mark)

    def mark(self, owner_id: str, aspect: str) -> None:
        self._dirty.add((owner_id, aspect))
        if not self._paused:
            self._timer.start()  # Restarts on every change.

    def stop(self) -> None:
        """Disarm for good — called when this build is discarded. A later flush against a
        replaced repository would be a stale write."""
        self._timer.stop()
        self._unsubscribe()

    # -- pausing (a checkout must not race a half-written file) --------------------------------

    def pause(self) -> None:
        self._paused += 1
        self._timer.stop()

    def resume(self) -> None:
        self._paused = max(0, self._paused - 1)
        if self._dirty and not self._paused:
            self._timer.start()

    def has_pending(self) -> bool:
        return bool(self._dirty)

    # -- flushing ------------------------------------------------------------------------------

    def flush_now(self) -> None:
        """Write everything pending, now. Called on tab switches, before quitting, and
        before any storage operation that touches the working tree."""
        if self._paused or not self._dirty:
            return
        dirty, self._dirty = self._dirty, set()
        self._timer.stop()
        try:
            self._persister.flush(dirty)
        except Exception as error:
            self._dirty |= dirty
            self.pause()
            self.failed.emit(error)
            return
        self.flushed.emit()
