"""Noticing that the workspace changed underneath the running window.

The framework's contract is "memory is authoritative, disk follows", which holds right up
until something else writes to the same folder — a CLI run, an agent, a colleague's merge.
This is the smallest thing that makes that safe: ask the repository whether the workspace
changed, on a timer, and hand the answer to whoever decides what to do about it.

It asks the *repository*, not the filesystem, because the repository already knows what it
last read and wrote. Two implementations of "did this change?" would drift, and the one that
matters is the one the store checks before it writes.
"""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QObject, QTimer

from dplanner.core.signals import Signal

# Slow enough to be free, quick enough that a person who alt-tabs back from an agent does
# not sit looking at stale content.
POLL_MS = 2000


@runtime_checkable
class WatchableRepository(Protocol):
    """A repository that can say whether its files changed since it last touched them."""

    def changed_underneath(self) -> bool: ...


class WorkspaceWatcher(QObject):
    """Polls a repository and emits once each time the workspace changes underneath it."""

    def __init__(self, repo: WatchableRepository, is_busy: Callable[[], bool]) -> None:
        super().__init__()
        self.changed: Signal[()] = Signal()
        self._repo = repo
        self._is_busy = is_busy
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._check)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        # Not while a write of our own is pending: the files are about to change because of
        # us, and reporting that as somebody else's edit would be a lie the user acts on.
        if self._is_busy() or not self._repo.changed_underneath():
            return
        self.changed.emit()
