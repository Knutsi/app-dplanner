"""Getting a workspace onto the machine, off the GUI thread.

Listing and cloning GitHub repositories are network calls, so they run through a
:class:`TaskRunner` like everything else slow. The result comes back on the GUI thread as a
Qt signal, and the caller switches the session to it.

Nothing here decides *which* provider to use — that is
:func:`dplanner.core.storage.locations.open_storage`'s job, and it decides from what is
actually on disk. This service only makes sure the disk has something to decide about.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from dplanner.core.storage.github import GitHubStorage, gh_authenticated, gh_path
from dplanner.core.storage.locations import StorageLocation, clone_target
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService

logger = logging.getLogger(__name__)


class WorkspaceService(QObject):
    repositories_loaded = Signal(list)  # list[str] of "owner/repo".
    cloned = Signal(object)  # StorageLocation, ready to open.
    failed = Signal(str)

    def __init__(self, clone_into: Path, tasks: TaskService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.clone_into = clone_into
        self._runner = TaskRunner(tasks, parent=self)
        self._runner.failed.connect(self.failed)

    @staticmethod
    def github_available() -> bool:
        """Whether GitHub is reachable at all. Advisory — checked before offering the UI."""
        return gh_path() is not None and gh_authenticated()

    def load_repositories(self) -> bool:
        def body() -> None:
            self.repositories_loaded.emit(GitHubStorage.list_repositories())

        return self._runner.run("Listing repositories", body, key="workspaces.list")

    def clone(self, repo: str) -> bool:
        """Clone ``owner/repo`` into the configured directory and announce where it landed."""
        location = StorageLocation(scheme="github", target=repo)
        dest = clone_target(location, self.clone_into)

        def body() -> None:
            if not (dest / ".git").exists():
                GitHubStorage.clone(repo, dest)
            # Opened by its local path from here on: what is on disk is the truth, and the
            # path form survives the repository being renamed on the server.
            self.cloned.emit(StorageLocation(scheme="", target=str(dest)))

        return self._runner.run(f"Cloning {repo}", body, key="workspaces.clone")
