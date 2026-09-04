"""Runs one blocking body at a time on a daemon thread, visible as a Task.

The one threading shell for slow work: storage commits, pushes, clones and LLM calls all
run their blocking bodies through a ``TaskRunner`` instead of carrying their own busy flag
and thread. Completion and progress are marshalled back to the GUI thread through queued
Qt signals, so every busy-state transition happens on the GUI thread and no locks exist.

The worker thread must never hold the last reference to anything Qt-related. PySide
deletes a Python-owned QObject the moment its last Python reference goes, on whatever
thread that happens; a worker that still held the runner (or the service its body closed
over) after queueing its completion could drop that last reference, deleting the QObject
while the GUI thread delivers the very event just queued for it — a segfault inside
``QCoreApplication::notify``, some time later, somewhere else. So the worker keeps only
the signal instance (which holds no reference to its QObject) and a :class:`_Handoff`
carrying the runner, the body and the task, and the GUI thread empties that handoff —
on the next turn of the event loop, the way ``deleteLater`` works — once the completion
has been delivered. Whatever the worker still holds afterwards is an empty shell.

Cancellation is cooperative: the body polls ``cancel_requested()`` at its safe points
and simply returns; the runner cannot tear a body down. Owners that want a task to
outlive its finish in the task centre pass ``keep_finished=True`` (see tasks.py).
The cancel/progress/detail knobs exist for long AI work; a storage commit deliberately
uses none of them — one must not be torn down halfway.
"""

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

from dplanner.framework.tasks import Task, TaskService

logger = logging.getLogger(__name__)


class TaskTimeoutError(RuntimeError):
    """Raised by a body whose underlying operation timed out; the task then finishes as
    timed out — a distinct terminal state, not a generic failure."""


class _Handoff:
    """Everything the worker thread may hold: the runner, the body and its task.

    The worker calls the body through here rather than through a local of its own, and
    the completion handler schedules ``release`` on the GUI thread for the next turn of
    the event loop: from no slot of the runner (releasing the body may free the runner's
    owner, and with it the runner) and after the worker has let go of the handoff itself
    (it may still be inside ``emit`` when the completion is delivered).
    """

    def __init__(self, runner: "TaskRunner", body: Callable[[], None], task: Task) -> None:
        self.runner = runner
        self.body = body
        self.task = task

    def run_body(self) -> None:
        self.body()

    def release(self) -> None:
        del self.runner, self.body, self.task


class TaskRunner(QObject):
    """GUI-thread API: ``run()`` / ``is_busy()``. Worker-side helpers, callable from
    inside the body: ``cancel_requested()`` and ``report_progress()``."""

    busy_changed = Signal(bool)  # Drives hooks like autosave pause/resume.
    failed = Signal(str)  # The body raised; emitted after busy_changed(False).

    # Worker → GUI marshals (queued by Qt because they're emitted off-thread). The handoff
    # carries the task, so a completion that no longer matches the runner's is dropped.
    _completed = Signal(object, str, bool)  # (_Handoff, "" on success else error, timed out).
    _progress = Signal(float)

    def __init__(self, tasks: TaskService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks = tasks
        self._task: Task | None = None
        self._completed.connect(self._on_completed)
        self._progress.connect(self._on_progress)

    def is_busy(self) -> bool:
        return self._task is not None

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
        handoff = _Handoff(self, body, self._task)
        completed = self._completed

        def work() -> None:
            error, timed_out = "", False
            try:
                handoff.run_body()
            except TaskTimeoutError:
                timed_out = True
            except Exception as exc:  # Slow work fails for mundane reasons; report it.
                error = str(exc) or type(exc).__name__
            try:
                completed.emit(handoff, error, timed_out)
            except RuntimeError as exc:
                # The runner's C++ side is gone: its owner was torn down (a
                # session close) while the body ran. Nothing is left to deliver to.
                logger.warning("task completion dropped, runner deleted mid-run: %s", exc)

        threading.Thread(target=work, daemon=True).start()
        return True

    def cancel_requested(self) -> bool:
        task = self._task
        return task is not None and task.cancel_requested

    def report_progress(self, fraction: float) -> None:
        self._progress.emit(fraction)

    def _on_progress(self, fraction: float) -> None:
        if self._task is not None:  # A late report arriving after finish is dropped.
            self._tasks.set_progress(self._task, fraction)

    def _on_completed(self, handoff: object, error: str, timed_out: bool) -> None:
        assert isinstance(handoff, _Handoff)
        task = handoff.task
        QTimer.singleShot(0, handoff.release)  # See _Handoff: next turn, not in this slot.
        if task is not self._task:  # A completion after the runner was reset: dropped.
            return
        self._task = None
        self._tasks.finish(task, error=error or None, timed_out=timed_out)
        # busy_changed(False) first: a failed handler may open a modal dialog, and
        # resume hooks (autosave) must not wait behind it.
        self.busy_changed.emit(False)
        if error:
            logger.warning("%s failed: %s", task.label, error)
            self.failed.emit(error)
