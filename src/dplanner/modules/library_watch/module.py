"""Two writers, one library — the window's half of the arrangement.

The point of DPlanner's CLI is that an agent can work on a project *while a window is open
on it*. That makes the framework's ordinary contract — memory is authoritative, disk
follows — incomplete, and this module supplies the missing half. The watch spans every
project directory *and* the library file itself, so another instance adding a project
arrives here the same way an agent's edit does:

**When something changes and nothing is pending, reload.** The reload path already
exists (``AppSession.reload`` rebuilds the whole application, which is what makes it
correct), so this only decides when to take it. Open tabs and undo history are lost, and
that is the honest price of a rebuild; it only happens when somebody really did write to a
folder.

**When something changes and the window has its own unflushed edits, stop and say so.**
The store refuses the write rather than erasing the other writer, autosave pauses itself, and
the choice becomes the user's: reload and lose what they typed, or keep it and overwrite.
Nobody can make that call for them, so nothing tries.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import Context
from dplanner.framework.session import SessionControl
from dplanner.framework.widgets import confirm
from dplanner.framework.window import StatusHost
from dplanner.framework.window_watch import WatchableRepository, WorkspaceWatcher

MODULE_ID = "library_watch"

RELOADED = "Reloaded — the library changed outside DPlanner"
CONFLICT = "A project changed outside DPlanner, and there are unsaved edits here"


@dataclass(frozen=True)
class LibraryWatchDeps:
    repo: WatchableRepository
    autosave: AutosaveService
    actions: ActionRegistry
    switcher: SessionControl
    status: StatusHost
    parent: QWidget


class LibraryWatchModule:
    id = MODULE_ID

    def __init__(self, deps: LibraryWatchDeps) -> None:
        self._deps = deps
        self._conflicted = False
        self._watcher = WorkspaceWatcher(deps.repo, deps.autosave.has_pending)

    def register(self) -> None:
        deps = self._deps
        self._watcher.changed.connect(self._on_changed)
        deps.autosave.failed.connect(self._on_refused)
        deps.actions.register(
            ActionSpec(
                id="library_watch.reload",
                label="Re&load from Disk",
                menu="File",
                group="library",
                order=90,
                tip="Discard what is in this window and read the library again",
                state=self._state,
                run=self._reload,
            )
        )
        self._watcher.start()

    # -- what happens ---------------------------------------------------------------------------

    def _on_changed(self) -> None:
        """Something wrote to the folder and this window owes it nothing: take the change."""
        self._deps.switcher.reload()
        self._deps.status.show_status(RELOADED, 4000)

    def _on_refused(self, _error: Exception) -> None:
        """The store declined to write because the folder moved under it.

        Autosave has already paused itself and kept the marks, so nothing is lost yet and
        nothing keeps retrying. All that is left is to tell the user, and to leave Reload
        enabled so they can choose.
        """
        self._conflicted = True
        self._watcher.stop()
        self._deps.status.show_status(CONFLICT)

    def _state(self, _context: Context) -> ActionState:
        return ENABLED if self._conflicted or not self._deps.autosave.has_pending() else DISABLED

    def _reload(self, _context: Context) -> None:
        if self._deps.autosave.has_pending() and not confirm(
            self._deps.parent,
            "Reload from Disk",
            "Reading the library again will discard the edits in this window. Continue?",
        ):
            return
        # Leave autosave paused: this build is about to be thrown away whole, and a flush
        # racing the rebuild is the exact thing the pause counter exists to prevent.
        self._deps.switcher.reload()
