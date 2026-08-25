"""The Qt side of storage: blocking provider calls, run as tasks.

The provider in :mod:`dplanner.core.storage` is Qt-free and every interesting method on it
blocks. This class is the bridge — it owns a :class:`TaskRunner`, so every commit, push and
pull shows up in the task centre while it runs, and re-emits the provider's Qt-free signals
as Qt ones so widgets can connect to them.

That is the whole reason this file exists. Keeping the split means the storage layer stays
testable with plain pytest and the threading discipline stays in one place, instead of every
backend inventing its own busy flag.

``before_operation`` is pointed at ``AutosaveService.pause`` by the module: no flush may
race a checkout that is rewriting the same files.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from dplanner.core.storage.provider import RemoteStorage, StorageError, VersionedStorage
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService

logger = logging.getLogger(__name__)


class SyncService(QObject):
    """Runs one storage operation at a time, visibly."""

    busy_changed = Signal(bool)
    notice = Signal(str)  # Status-bar messages: "Saved", "Nothing to save".
    failed = Signal(str)
    branch_changed = Signal(str)
    # Files were rewritten under the running application: the workspace must be rebuilt.
    worktree_changed = Signal()
    dirty_changed = Signal(bool, int)  # (has uncommitted changes, changed file count)

    def __init__(
        self, storage: VersionedStorage, tasks: TaskService, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.branch = ""
        self.dirty = False
        self.dirty_file_count = 0
        # Storage operations are deliberately not cancellable: one must not be torn down
        # halfway. They do show in the task centre, which is what the user actually wants.
        self._runner = TaskRunner(tasks, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)
        self._runner.failed.connect(self.failed)
        # Set by the module to AutosaveService.pause — see this module's docstring.
        self.before_operation: Callable[[], None] | None = None

        self._unsubscribes = [
            storage.dirty_changed.connect(self._on_dirty),
            storage.worktree_changed.connect(self.worktree_changed.emit),
        ]

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- state ---------------------------------------------------------------------------------

    @property
    def remote(self) -> RemoteStorage | None:
        """The provider as a remote-capable one, or None when it has nowhere to push."""
        storage = self.storage
        if isinstance(storage, RemoteStorage) and storage.has_remote():
            return storage
        return None

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def refresh(self) -> None:
        """Re-read the local state. Cheap: no network, so it runs after every flush."""
        self.storage.refresh_dirty()
        branch = self.storage.current_branch()
        if branch != self.branch:
            self.branch = branch
            self.branch_changed.emit(branch)

    def _on_dirty(self, dirty: bool, count: int) -> None:
        self.dirty, self.dirty_file_count = dirty, count
        self.dirty_changed.emit(dirty, count)

    def _start(self, label: str, body: Callable[[], None]) -> bool:
        if self._runner.is_busy():
            self.notice.emit("Storage is busy — try again in a moment")
            return False
        if self.before_operation is not None:
            self.before_operation()
        return self._runner.run(label, body)

    # -- operations ----------------------------------------------------------------------------

    def save_sync(self, message: str = "") -> None:
        """Commit, then push when there is a remote. Directly testable, no threads."""
        committed = self.storage.commit(message)
        remote = self.remote
        if remote is not None:
            remote.push()
        if committed:
            self.notice.emit("Saved" + (" and pushed" if remote is not None else ""))
        else:
            self.notice.emit("Nothing new to save")

    def save(self, message: str = "") -> bool:
        return self._start("Saving", lambda: self.save_sync(message))

    def pull_sync(self) -> None:
        remote = self.remote
        if remote is None:
            return
        self.notice.emit("Updated" if remote.pull() else "Already up to date")

    def pull(self) -> bool:
        return self._start("Updating", self.pull_sync)

    def switch_branch_sync(self, name: str) -> None:
        self.storage.switch_branch(name)
        self.refresh()
        self.notice.emit(f"Switched to {name}")

    def create_branch_sync(self, name: str) -> None:
        self.storage.create_branch(name)
        self.refresh()
        self.notice.emit(f"Started {name}")

    def branches(self) -> list[str]:
        try:
            return self.storage.branches()
        except StorageError:
            logger.exception("could not list branches")
            return []
