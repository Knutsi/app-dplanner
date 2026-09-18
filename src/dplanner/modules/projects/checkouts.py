"""Getting a repository onto this machine for a verb that needs it.

Run Agent on code nobody checked out, a report published to a repository this machine
lacks: the verb asks here and gets a checkout — the one recorded already, or a clone made
now on a task and recorded for next time. The **clone policy** (`repositories_folder.py`)
decides the destination only: kept by DPlanner under its configuration directory, or in the
person's repositories folder, asked once. It never decides whether the verb runs, which is
what retired the *not checked out on this machine* dead end from every verb that can clone.

One request at a time, in order: a second ``ensure`` while one clones waits its turn, so a
Run Agent over three steps in two repositories clones two and launches three. Everything
lands on the GUI thread — the record through ``services.set_checkout``, the answer through
``done`` — because a clone is a `TaskRunner` body and the model is never touched off it.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QWidget

from dplanner.core.storage.kept import kept_dir
from dplanner.core.storage.locations import remote_label
from dplanner.core.storage.provider import StorageError
from dplanner.core.storage.sparse import GitError, refusal
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.projects.repos import RepositoryServices, shown_path
from dplanner.modules.projects.repositories_folder import (
    KEPT,
    clone_policy,
    ensure_repositories_folder,
)

# The answer: the checkout's root, or None with why not.
Done = Callable[[Path | None, str], None]
# The answer for several: what landed by repository, and the first refusal or "".
ManyDone = Callable[[dict[str, Path], str], None]
CANCELLED = "no folder was chosen for the clone"


def repo_folder_name(remote: str) -> str:
    """The folder a clone of ``remote`` lands in: the repository's own name."""
    return remote_label(remote).rsplit("/", 1)[-1] or "repository"


class CheckoutService(QObject):
    """Where a verb gets a repository on this machine; see the module docstring."""

    _landed = QtSignal(str, object, str)  # (repository, Path | None, error) — queued.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        *,
        kept_root: Path,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._kept_root = kept_root
        self._parent = parent
        self._runner = TaskRunner(tasks, parent=self)
        self._landed.connect(self._on_landed)
        self._queue: list[tuple[str, Done]] = []
        self._current: tuple[str, Done] | None = None

    # -- asking ------------------------------------------------------------------------------

    @property
    def kept_root(self) -> Path:
        """The configuration directory kept clones live under — what a placement is
        read against to say *kept by DPlanner*."""
        return self._kept_root

    def where(self, repository: str) -> str:
        """Where a clone of ``repository`` would land, for a verb's label: ``kept by
        DPlanner`` or ``into the repositories folder``."""
        return "kept by DPlanner" if clone_policy() == KEPT else "into the repositories folder"

    def destination(self, repository: str) -> Path | None:
        """Where a clone of ``repository`` lands under the policy; None when the person
        was asked for a repositories folder and cancelled."""
        if clone_policy() == KEPT:
            return kept_dir(self._kept_root, repository)
        folder = ensure_repositories_folder(self._parent)
        return None if folder is None else folder / repo_folder_name(repository)

    def ensure(self, repository: str, done: Done) -> None:
        """A checkout of ``repository`` on this machine: at once when one is recorded,
        else cloned where the policy says, recorded, and answered."""
        known = self._services.checkout_for(repository)
        if known is not None and known.expanduser().is_dir():
            done(known, "")
            return
        self._queue.append((repository, done))
        self._next()

    def ensure_many(self, repositories: Sequence[str], done: ManyDone) -> None:
        """Every repository in turn; the answer once the last has landed or refused."""
        landed: dict[str, Path] = {}
        pending = list(dict.fromkeys(repositories))
        if not pending:
            done(landed, "")
            return

        def one_done(repository: str) -> Done:
            def answer(root: Path | None, error: str) -> None:
                if root is not None:
                    landed[repository] = root
                pending.remove(repository)
                if error:
                    done(landed, f"{remote_label(repository)}: {error}")
                    pending.clear()
                elif not pending:
                    done(landed, "")

            return answer

        for repository in list(pending):
            self.ensure(repository, one_done(repository))

    # -- the clone ---------------------------------------------------------------------------

    def _next(self) -> None:
        if self._current is not None or not self._queue:
            return
        repository, done = self._queue.pop(0)
        dest = self.destination(repository)
        if dest is None:
            done(None, CANCELLED)
            self._next()
            return
        if (dest / ".git").exists():
            self._record(repository, dest)
            done(dest, "")
            self._next()
            return
        if dest.exists():
            done(None, f"{shown_path(dest)} exists and is not a repository")
            self._next()
            return
        self._current = (repository, done)
        clone_url = self._services.clone_url
        landed = self._landed

        def body() -> None:  # Worker thread: two values and a function, never the model.
            try:
                clone_url(repository, dest)
                landed.emit(repository, dest, "")
            except GitError as error:
                landed.emit(repository, None, refusal(error, repository, "HEAD").sentence)
            except (StorageError, OSError, ValueError) as error:
                landed.emit(repository, None, str(error))

        label = remote_label(repository)
        if not self._runner.run(f"Cloning {label}", body, key="projects.checkout"):
            self._current = None
            done(None, "still busy with the last clone — try again in a moment")
            self._next()

    def _on_landed(self, repository: str, root: object, error: str) -> None:
        current, self._current = self._current, None
        if current is None:
            return
        _repository, done = current
        if isinstance(root, Path) and not error:
            self._record(repository, root)
            done(root, "")
        else:
            done(None, error or "the clone did not land")
        self._next()

    def _record(self, repository: str, root: Path) -> None:
        self._services.set_checkout(repository, root)
