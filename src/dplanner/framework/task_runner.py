"""Runs one blocking body at a time on a daemon thread, visible as a Task.

The one threading shell for slow work: storage commits, pushes, clones and LLM calls all
run their blocking bodies through a ``TaskRunner`` instead of carrying their own busy flag
and thread. Completion and progress are marshalled back to
the GUI thread through queued Qt signals, so every busy-state transition happens on the
GUI thread and no locks exist.

Cancellation is cooperative: the body polls ``cancel_requested()`` at its safe points
and simply returns; the runner cannot tear a body down. Owners that want a task to
outlive its finish in the task centre pass ``keep_finished=True`` (see tasks.py).
The cancel/progress/detail knobs exist for long AI work; a storage commit deliberately
uses none of them — one must not be torn down halfway.
"""

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from dplanner.framework.tasks import Task, TaskService

logger = logging.getLogger(__name__)


class TaskTimeoutError(RuntimeError):
    """Raised by a body whose underlying operation timed out; the task then finishes as
    timed out — a distinct terminal state, not a generic failure."""


class TaskRunner(QObject):
    """GUI-thread API: ``run()`` / ``is_busy()``. Worker-side helpers, callable from
    inside the body: ``cancel_requested()`` and ``report_progress()``."""

    busy_changed = Signal(bool)  # Drives hooks like autosave pause/resume.
    failed = Signal(str)  # The body raised; emitted after busy_changed(False).

    # Worker → GUI marshals (queued by Qt because they're emitted off-thread). The task
    # travels with the completion so a late completion from an abandoned run is dropped.
    _completed = Signal(object, str, bool)  # (task, "" on success else error, timed out).
    _progress = Signal(float)

    def __init__(self, tasks: TaskService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks = tasks
        self._task: Task | None = None
        self._completed.connect(self._on_completed)
        self._progress.connect(self._on_progress)

    def is_busy(self) -> bool:
        return self._task is not None

    def current_task(self) -> Task | None:
        """The running body's task — None when idle. Owners that track per-target runs
        (a task per item, say) grab it right after ``run()`` returns True."""
        return self._task

    def run(
        self,
        label: str,
        body: Callable[[], None],
        *,
        key: str | None = None,
        cancellable: bool = False,
        cancel_prompt: str | None = None,
        keep_finished: bool = False,
        detail_factory: Callable[[], QWidget] | None = None,
    ) -> bool:
        """Start ``body`` on a daemon thread under a new Task. False when already busy —
        the caller keeps its own refusal message ("Git is busy…")."""
        if self._task is not None:
            return False
        self._task = self._tasks.start(
            label,
            key,
            cancellable=cancellable,
            cancel_prompt=cancel_prompt,
            keep_finished=keep_finished,
            detail_factory=detail_factory,
        )
        self.busy_changed.emit(True)
        task = self._task

        def work() -> None:
            try:
                body()
            except TaskTimeoutError:
                self._completed.emit(task, "", True)
            except Exception as error:  # Slow work fails for mundane reasons; report it.
                self._completed.emit(task, str(error) or type(error).__name__, False)
            else:
                self._completed.emit(task, "", False)

        threading.Thread(target=work, daemon=True).start()
        return True

    def abandon(self) -> None:
        """Give up waiting for the current body: finish its task now and free the runner
        for new work. The daemon thread keeps running to completion, but its late
        completion no longer matches ``self._task`` and is dropped. This is the escape
        hatch for a body stuck in blocking I/O that cooperative cancel cannot reach."""
        task, self._task = self._task, None
        if task is None:
            return
        self._tasks.finish(task)  # With cancel_requested set this counts as cancelled.
        self.busy_changed.emit(False)

    def cancel_requested(self) -> bool:
        task = self._task
        return task is not None and task.cancel_requested

    def report_progress(self, fraction: float) -> None:
        self._progress.emit(fraction)

    def _on_progress(self, fraction: float) -> None:
        if self._task is not None:  # A late report arriving after finish is dropped.
            self._tasks.set_progress(self._task, fraction)

    def _on_completed(self, task: Task, error: str, timed_out: bool) -> None:
        if task is not self._task:  # An abandoned run's task was already finished.
            return
        self._task = None
        self._tasks.finish(task, error=error or None, timed_out=timed_out)
        # busy_changed(False) first: a failed handler may open a modal dialog, and
        # resume hooks (autosave) must not wait behind it.
        self.busy_changed.emit(False)
        if error:
            logger.warning("%s failed: %s", task.label, error)
            self.failed.emit(error)
