"""Noticing that the workspace changed underneath the running window.

The framework's contract is "memory is authoritative, disk follows", which holds right up
until something else writes to the same folder — a CLI run, an agent, a colleague's merge.
This is the smallest thing that makes that safe: ask the repository whether the workspace
changed, on a timer, and hand the answer to whoever decides what to do about it.

It asks the *repository*, not the filesystem, because the repository already knows what it
last read and wrote. Two implementations of "did this change?" would drift, and the one that
matters is the one the store checks before it writes. The same repository is what takes the
change in — :meth:`WatchableRepository.adopt_outside_changes` — so the poll is also the
debounce: however many writes land inside one interval, they are adopted once.
"""

from collections.abc import Collection
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QObject, QTimer

from dplanner.core.signals import Signal
from dplanner.core.telemetry import current
from dplanner.domain.store import Adoption, Conflict

# Slow enough to be free, quick enough that a person who alt-tabs back from an agent does
# not sit looking at stale content.
POLL_MS = 2000


@runtime_checkable
class WatchableRepository(Protocol):
    """A repository that can say whether its files changed since it last touched them, and
    read what changed into the document it holds."""

    def changed_underneath(self) -> bool: ...

    def adopt_outside_changes(self, *, take: Collection[Conflict] = ()) -> Adoption: ...

    def mark_seen(self, conflicts: Collection[Conflict]) -> None: ...


class WorkspaceWatcher(QObject):
    """Polls a repository and emits once each time the workspace changes underneath it."""

    def __init__(self, repo: WatchableRepository) -> None:
        super().__init__()
        self.changed: Signal[()] = Signal()
        self._repo = repo
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._check)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        # No guard for this window's own pending writes: a flush re-stamps the record as
        # it writes, so what this window did never reads as somebody else's, and an entry
        # both sides changed is the store's per-entry conflict, not the watcher's business.
        # Timed: a walk over every plan file, on the GUI thread, every two seconds — a
        # slow one shows up as a poll span, a quick one is not kept.
        with current().span("poll", "workspace"):
            changed = self._repo.changed_underneath()
        if changed:
            self.changed.emit()
