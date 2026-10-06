"""Background maintenance: keep each stored PR's last-seen state current.

Only PRs whose stored state is ``open`` or "" (never checked) are re-checked — merged and
closed are terminal, and a reopened PR is rare enough that ``dplanner github refresh`` or
setting the ref again covers it.

**The refreshed state is applied directly, never pushed onto the undo stack.** It is a
cache of an external fact, not a user decision: an undo entry here would make Ctrl+Z
restore a *stale* PR state instead of undoing the user's last edit. The command still runs
— every model change goes through one — with this module's own origin, exactly as the CLI
and the format migrations apply theirs. Autosave flushes on the store's dirty signal, so
the write reaches disk without the stack's help, and the stale-workspace guard already
covers an agent writing concurrently. ``docs/architecture/persistence.md``'s *Syncing an external
fact* has the reasoning.

**A merged PR finishes a step waiting on its merge** — *ready to merge* means exactly that
the PR is what is left — through ``finish_merged``, the status aspect's writer handed over by
the composition root, applied the same way. Every tick also offers it the steps whose PR
already read merged, since a step can reach *ready to merge* after its PR did: a review
approved once the developer had merged, carrying a state nobody fetches again.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtCore import Signal as QtSignal

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, StepId
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.github.aspect import MODULE_ID, PR_MERGED, PR_OPEN, read, refreshed, write
from dplanner.modules.github.gh import GhError, PrInfo, gh_refusal, parse_repo, view_pr

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 5 * 60 * 1000

# The refresher's origin: no view claims it, so every surface treats the write as foreign
# and repaints — which is right, the state just changed under all of them.
REFRESH_ORIGIN: object = object()


def _nothing_to_finish(_step_id: StepId) -> bool:
    """A build with no status to move: a merge finishes nothing."""
    return False


def adopt(
    library: Library,
    step_id: StepId,
    info: PrInfo,
    finish_merged: Callable[[StepId], bool],
) -> None:
    """What GitHub just said about a step's PR, written the refresher's way — directly,
    with its origin, never onto the undo stack — and the step finished if it was waiting
    on this merge. The one writer the refresher and the GitHub tab share."""
    refs = read(library.step(step_id))
    if refs is None:
        return
    fresh = refreshed(refs, info)
    if fresh != refs:
        SetModuleDataCommand(
            step_id, MODULE_ID, write(fresh), view_origin=REFRESH_ORIGIN, label=""
        ).redo(library)
    if fresh.pr_state == PR_MERGED:
        finish_merged(step_id)


class PrRefresher(QObject):
    """Checks open PRs against GitHub on a timer, off the GUI thread."""

    # Worker → GUI: fetched states, queued because they are emitted off-thread.
    _fetched = QtSignal(object)  # list[tuple[StepId, PrInfo]]
    _refused = QtSignal(str)

    def __init__(
        self,
        library: Library,
        tasks: TaskService,
        repository_for: Callable[[StepId], str],
        parent: QObject,
        finish_merged: Callable[[StepId], bool] = _nothing_to_finish,
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._repository_for = repository_for
        self._finish_merged = finish_merged
        self._runner = TaskRunner(tasks, parent=self)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        # The first tick is a timer of its own rather than a bare ``QTimer.singleShot``, so
        # that :meth:`stop` can reach it. An untracked one is already queued by the time
        # anybody could ask to stop, and it fires into whatever the world looks like then.
        self._first = QTimer(self)
        self._first.setSingleShot(True)
        self._first.timeout.connect(self._tick)
        self._fetched.connect(self._apply)
        self._refused.connect(self._stop)

    def start(self) -> None:
        # Once now — the work leaves the GUI thread immediately — then on the interval.
        self._first.start(0)
        self._timer.start()

    def stop(self) -> None:
        """Ask no more, including the first time. Both timers, because ``start`` set both."""
        self._first.stop()
        self._timer.stop()

    def _tick(self) -> None:
        # Snapshot on the GUI thread: the model has no thread affinity and may only be
        # read here — the worker body sees plain ids, numbers and repo names, never the
        # library. Each step carries its own repo, because a project can override the
        # library's repository.
        for project in self._product.projects:
            for step in project.steps:
                if (refs := read(step)) is not None and refs.pr_state == PR_MERGED:
                    self._finish_merged(step.id)
        targets = [
            (step.id, refs.pr_number, repo)
            for project in self._product.projects
            for step in project.steps
            if (refs := read(step)) is not None
            and refs.pr_number is not None
            and refs.pr_state in (PR_OPEN, "")
            and (repo := parse_repo(self._repository_for(step.id))) is not None
        ]
        if not targets:
            return

        def body() -> None:
            refusal = gh_refusal(check_auth=True)
            if refusal is not None:
                self._refused.emit(refusal)
                return
            found: list[tuple[StepId, PrInfo]] = []
            for step_id, number, repo in targets:
                if self._runner.cancel_requested():
                    return
                try:
                    info = view_pr(repo, number)
                except GhError as error:
                    logger.info("PR #%s: %s", number, error)
                    continue
                if info is not None:
                    found.append((step_id, info))
            self._fetched.emit(found)

        # False when a previous refresh is still running: skip this tick, never queue.
        self._runner.run("Checking pull requests", body, key="github.refresh")

    def _apply(self, results: object) -> None:
        if not isinstance(results, list):
            return
        for step_id, info in results:
            if not self._product.has(step_id):
                continue  # The step went away while the worker was out.
            refs = read(self._product.step(step_id))
            if refs is None or refs.pr_number != info.number:
                continue  # The ref changed underneath; this answer is about the old PR.
            adopt(self._product, step_id, info, self._finish_merged)

    def _stop(self, refusal: str) -> None:
        """gh cannot be used: stop asking for this session rather than fail every tick."""
        self.stop()
        logger.info("PR refresh stopped: %s", refusal)
