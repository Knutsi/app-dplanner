"""Two writers, one library — the window's half of the arrangement.

The point of DPlanner's CLI is that an agent can work on a project *while a window is open
on it*. That makes the framework's ordinary contract — memory is authoritative, disk
follows — incomplete, and this module supplies the missing half. The watch spans every
project directory *and* the library file itself, so another instance adding a project
arrives here the same way an agent's edit does.

**When something changes, take it in place.** ``SessionControl.refresh`` has the store read
what changed into the live model, entry by entry, and every view repaints as it would for
any foreign edit — the window, its tabs, its selection and its undo history all stay. The
whole rebuild is only what refresh falls back to when the store cannot read what it found.

**An entry both sides changed is the user's call.** The store adopts everything else and
reports the collision; autosave stays paused (its refused batch keeps the edit safe) while a
modal offers the ways out: hand both versions to the configured agent — Run Agent's
launcher, reached through the root — take theirs, keep ours, or later. Nobody else can make
that call, so nothing tries; *Later* leaves a status-bar button that reopens the question.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, StepId
from dplanner.domain.store import Conflict
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import Context
from dplanner.framework.session import RefreshResult, SessionControl
from dplanner.framework.widgets import confirm
from dplanner.framework.window import StatusHost
from dplanner.framework.window_watch import WatchableRepository, WorkspaceWatcher
from dplanner.modules.library_watch.view import (
    AGENT,
    LATER,
    MINE,
    THEIRS,
    ConflictDialog,
    OutsideChangesButton,
)

MODULE_ID = "library_watch"

NO_STEP = "only a step's entries can be handed to an agent"


@dataclass(frozen=True)
class LibraryWatchDeps:
    repo: WatchableRepository
    autosave: AutosaveService
    actions: ActionRegistry
    switcher: SessionControl
    status: StatusHost
    parent: QWidget
    library: Library  # Names the nodes a conflict is on.
    # Hands a step's conflicting entries to the configured agent (True when a shell was
    # spawned), and why that is not possible right now ("" when it is). Both belong to the
    # agent module and arrive through the root; None is a build without one.
    hand_to_agent: Callable[[StepId, Sequence[Conflict]], bool] | None = None
    agent_refusal: Callable[[StepId], str] | None = None


class LibraryWatchModule:
    id = MODULE_ID

    def __init__(self, deps: LibraryWatchDeps) -> None:
        self._deps = deps
        self._watcher = WorkspaceWatcher(deps.repo)
        self._conflicts: tuple[Conflict, ...] = ()
        # The set the dialog was last raised for: a tick that finds the same conflicts
        # again — every tick, while they wait — must not raise it again.
        self._asked: frozenset[Conflict] = frozenset()
        self._button = OutsideChangesButton()
        # Raises the question out of the timer slot and the autosave cascade — a modal
        # from inside a flush would block whatever asked for it. Owned by the window, so a
        # refusal met on the way out (the close hook's last flush) asks nobody.
        self._ask_soon = QTimer(deps.parent)
        self._ask_soon.setSingleShot(True)
        self._ask_soon.setInterval(0)
        self._ask_soon.timeout.connect(self._ask)

    def register(self) -> None:
        deps = self._deps
        self._watcher.changed.connect(self._on_changed)
        deps.autosave.failed.connect(self._on_refused)
        deps.status.add_status_widget(self._button)
        self._button.clicked.connect(self._ask)
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
        """Something wrote to the folder: take it."""
        self._settle(self._deps.switcher.refresh())

    def _on_refused(self, error: Exception) -> None:
        """The store declined to write because the folder moved under it.

        Autosave has paused itself and kept the marks. Taking the outside change re-stamps
        the folder as seen, so the retry succeeds — unless an entry collided, in which case
        the question goes to the user and autosave stays paused until it is answered.
        """
        result = self._deps.switcher.refresh()
        if result.rebuilt:
            return  # This build, and this module with it, is being replaced.
        adoption = result.adoption
        if adoption is None or not (adoption.applied or adoption.conflicts):
            self._deps.status.show_status(str(error))  # Refused for a reason no take clears.
            return
        self._settle(result)
        if not adoption.conflicts:
            self._deps.autosave.resume()

    def _settle(self, result: RefreshResult) -> None:
        adoption = result.adoption
        if result.rebuilt or adoption is None:
            return
        if adoption.applied:
            noun = "change" if adoption.applied == 1 else "changes"
            self._deps.status.show_status(
                f"Took {adoption.applied} {noun} from outside DPlanner", 4000
            )
        self._conflicts = adoption.conflicts
        self._button.set_waiting(len(adoption.conflicts))
        waiting = frozenset(adoption.conflicts)
        if waiting and waiting != self._asked:
            self._asked = waiting
            self._ask_soon.start()
        elif not waiting:
            self._asked = frozenset()

    # -- the question ---------------------------------------------------------------------------

    def _ask(self) -> None:
        conflicts = self._conflicts
        deps = self._deps
        if not conflicts or not deps.parent.isVisible():
            return  # A window on its way out has nobody to ask.
        step_id = self._anchor(conflicts)
        if deps.hand_to_agent is None:
            refusal = "no agent in this build"
        elif step_id is None:
            refusal = NO_STEP
        else:
            refusal = deps.agent_refusal(step_id) if deps.agent_refusal is not None else ""
        choice = ConflictDialog(
            [self._describe(conflict) for conflict in conflicts], refusal, deps.parent
        ).choose()
        self._resolve(choice, conflicts, step_id)

    def _resolve(
        self, choice: str, conflicts: tuple[Conflict, ...], step_id: StepId | None
    ) -> None:
        deps = self._deps
        if choice == LATER:
            return
        if choice == AGENT:
            assert deps.hand_to_agent is not None and step_id is not None
            if not deps.hand_to_agent(step_id, conflicts):
                return  # No shell opened; the question stands.
            # The agent reads the window's version from its run directory and writes the
            # merge back into the plan, which arrives here like any outside change. Until
            # then the plan on disk is the truth, so this window yields to it.
            choice = THEIRS
        if choice == THEIRS:
            deps.repo.adopt_outside_changes(take=conflicts)
        elif choice == MINE:
            deps.repo.mark_seen(conflicts)
        self._conflicts = ()
        self._asked = frozenset()
        self._button.set_waiting(0)
        deps.autosave.resume()

    def _anchor(self, conflicts: Sequence[Conflict]) -> StepId | None:
        """The step an agent run is tracked on: the first step among the conflicts."""
        library = self._deps.library
        for conflict in conflicts:
            if library.has(conflict.node_id) and library.node(conflict.node_id).kind == "step":
                return conflict.node_id
        return None

    def _describe(self, conflict: Conflict) -> str:
        library = self._deps.library
        if not library.has(conflict.node_id):
            return conflict.path
        node = library.node(conflict.node_id)
        title = str(getattr(node, "title", "")) or "Untitled"
        if conflict.entry == "meta":
            what = "title and links" if node.kind == "step" else "title and summary"
        else:
            what = conflict.entry.rsplit(".", 1)[0].replace("_", " ")
        return f"{title} · {what}"

    # -- reload, the escape hatch ---------------------------------------------------------------

    def _state(self, _context: Context) -> ActionState:
        return ENABLED if self._conflicts or not self._deps.autosave.has_pending() else DISABLED

    def _reload(self, _context: Context) -> None:
        if self._deps.autosave.has_pending() and not confirm(
            self._deps.parent,
            "Reload from Disk",
            "Reading the library again will discard the edits in this window. Continue?",
        ):
            return
        # Leave autosave paused: this build is about to be thrown away whole, and a flush
        # racing the rebuild is the exact thing the pause counter exists to prevent.
        self._deps.autosave.pause()
        self._deps.switcher.reload()
