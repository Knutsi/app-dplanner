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
covers an agent writing concurrently. ``ARCHITECTURE.md``'s *Syncing an external fact* has
the reasoning.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtCore import Signal as QtSignal

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, StepId
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.github.aspect import MODULE_ID, read, refreshed, write
from dplanner.modules.github.gh import GhError, PrInfo, gh_refusal, parse_repo, view_pr

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 5 * 60 * 1000

# The refresher's origin: no view claims it, so every surface treats the write as foreign
# and repaints — which is right, the state just changed under all of them.
REFRESH_ORIGIN: object = object()


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
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._repository_for = repository_for
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
        targets = [
            (step.id, refs.pr_number, repo)
            for project in self._product.projects
            for step in project.steps
            if (refs := read(step)) is not None
            and refs.pr_number is not None
            and refs.pr_state in ("open", "")
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
            fresh = refreshed(refs, info)
            if fresh == refs:
                continue
            SetModuleDataCommand(
                step_id, MODULE_ID, write(fresh), view_origin=REFRESH_ORIGIN, label=""
            ).redo(self._product)

    def _stop(self, refusal: str) -> None:
        """gh cannot be used: stop asking for this session rather than fail every tick."""
        self.stop()
        logger.info("PR refresh stopped: %s", refusal)
