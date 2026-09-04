"""The Qt side of storage: blocking provider calls over every repository, run as tasks.

The providers in :mod:`dplanner.core.storage` are Qt-free and every interesting method on
them blocks. This class is the bridge — it owns a :class:`TaskRunner`, so every commit,
push and pull shows up in the task centre while it runs, and re-emits the providers'
Qt-free signals as Qt ones so widgets can connect to them.

One library spans several repositories, so the service holds a *list* of repository
groups — one provider per distinct git repository, scoped to that repository's project
directories — and its dirty state is the aggregate. The groups come from a callable
because membership changes at runtime: :meth:`rewire` re-pulls the list and re-subscribes,
and must be called when a project joins or leaves the library, or a subscription would be
left on a provider nothing holds any more.

``before_operation`` is pointed at ``AutosaveService.pause`` by the module: no flush may
race a checkout that is rewriting the same files.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QObject, Signal

from dplanner.core.storage.provider import (
    RemoteStorage,
    StorageError,
    StorageProvider,
    VersionedStorage,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService

logger = logging.getLogger(__name__)

# How long the status bar's branch label trusts its last answer from git.
BRANCH_CACHE_S = 1.0


@runtime_checkable
class RepoGroup(VersionedStorage, Protocol):
    """A repository group: versioned, and nameable in the UI.

    ``VersionedStorage`` is a capability protocol and deliberately does not promise
    ``label``; a group is always a whole provider, so it has one — this intersection is
    what lets the dialogs name what they commit."""

    @property
    def label(self) -> str: ...


class SyncService(QObject):
    """Runs one storage operation at a time, visibly, across the library's repositories."""

    busy_changed = Signal(bool)
    notice = Signal(str)  # Status-bar messages: "Saved", "Nothing to save".
    failed = Signal(str)
    # Files were rewritten under the running application: the library must be rebuilt.
    worktree_changed = Signal()
    dirty_changed = Signal(bool, int)  # (any uncommitted changes, changed file count total)

    def __init__(
        self,
        repos: Callable[[], Sequence[StorageProvider]],
        tasks: TaskService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repos = repos
        self._groups: list[RepoGroup] = []
        self._branches: dict[int, tuple[float, str]] = {}  # id(group) → (asked at, branch).
        self._unsubscribes: list[Callable[[], None]] = []
        self.dirty = False
        self.dirty_file_count = 0
        # Storage operations are deliberately not cancellable: one must not be torn down
        # halfway. They do show in the task centre, which is what the user actually wants.
        self._runner = TaskRunner(tasks, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)
        self._runner.failed.connect(self.failed)
        # Set by the module to AutosaveService.pause — see this module's docstring.
        self.before_operation: Callable[[], None] | None = None
        self.rewire()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- the groups ----------------------------------------------------------------------------

    def rewire(self) -> None:
        """Re-pull the repository groups and re-subscribe — membership changed."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._groups = [group for group in self._repos() if isinstance(group, RepoGroup)]
        self._branches.clear()
        for group in self._groups:
            self._unsubscribes.append(group.dirty_changed.connect(self._recount))
            self._unsubscribes.append(group.worktree_changed.connect(self.worktree_changed.emit))
        self._recount()

    def groups(self) -> list[RepoGroup]:
        return list(self._groups)

    def dirty_groups(self) -> list[RepoGroup]:
        return [group for group in self._groups if group.is_dirty()]

    # -- state ---------------------------------------------------------------------------------

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def refresh(self) -> None:
        """Re-read every repository's local state. No network, so it runs after every flush."""
        self._branches.clear()
        for group in self._groups:
            group.refresh_dirty()
        self._recount()

    def branch_of(self, group: RepoGroup) -> str:
        """The group's current branch, remembered for a second.

        The status bar's label asks on every context change — twice per keystroke, the
        journal showed — and the answer is a git subprocess. A branch changes through an
        operation here (which refreshes, clearing this) or under the running application
        (which the watcher takes in, and a second's staleness on a label is nothing).
        """
        now = time.monotonic()
        cached = self._branches.get(id(group))
        if cached is not None and now - cached[0] < BRANCH_CACHE_S:
            return cached[1]
        branch = group.current_branch()
        self._branches[id(group)] = (now, branch)
        return branch

    def _recount(self, *_args: object) -> None:
        dirty = any(group.is_dirty() for group in self._groups)
        count = sum(group.dirty_file_count() for group in self._groups)
        if dirty != self.dirty or count != self.dirty_file_count:
            self.dirty, self.dirty_file_count = dirty, count
            self.dirty_changed.emit(dirty, count)

    @staticmethod
    def _remote(group: RepoGroup) -> RemoteStorage | None:
        """The group as a remote-capable provider, or None when it has nowhere to push."""
        if isinstance(group, RemoteStorage) and group.has_remote():
            return group
        return None

    def _start(self, label: str, body: Callable[[], None]) -> bool:
        if self._runner.is_busy():
            self.notice.emit("Storage is busy — try again in a moment")
            return False
        if self.before_operation is not None:
            self.before_operation()
        return self._runner.run(label, body)

    # -- operations ----------------------------------------------------------------------------

    def save_sync(self, message: str = "", only: Sequence[RepoGroup] | None = None) -> None:
        """Commit every dirty repository — one commit per repo — pushing where possible.

        ``only`` narrows the sweep (the quit dialog's unchecked rows are left dirty).
        Directly testable, no threads.
        """
        targets = self._groups if only is None else list(only)
        saved, pushed = 0, 0
        for group in targets:
            group.refresh_dirty()
            if not group.is_dirty():
                continue
            if group.commit(message):
                saved += 1
                remote = self._remote(group)
                if remote is not None:
                    remote.push()
                    pushed += 1
        self._recount()
        if saved == 0:
            self.notice.emit("Nothing new to save")
        elif saved == 1:
            self.notice.emit("Saved" + (" and pushed" if pushed else ""))
        else:
            suffix = " and pushed" if pushed else ""
            self.notice.emit(f"Saved {saved} repositories{suffix}")

    def save(self, message: str = "") -> bool:
        return self._start("Saving", lambda: self.save_sync(message))

    def pull_sync(self) -> None:
        arrived = 0
        for group in self._groups:
            remote = self._remote(group)
            if remote is not None and remote.pull():
                arrived += 1
        self.notice.emit("Updated" if arrived else "Already up to date")

    def pull(self) -> bool:
        return self._start("Updating", self.pull_sync)

    def has_any_remote(self) -> bool:
        return any(self._remote(group) is not None for group in self._groups)

    def switch_branch_sync(self, group: RepoGroup, name: str) -> None:
        group.switch_branch(name)
        self.refresh()
        self.notice.emit(f"Switched to {name}")

    def create_branch_sync(self, group: RepoGroup, name: str) -> None:
        group.create_branch(name)
        self.refresh()
        self.notice.emit(f"Started {name}")

    def branches(self, group: RepoGroup) -> list[str]:
        try:
            return group.branches()
        except StorageError:
            logger.exception("could not list branches")
            return []
