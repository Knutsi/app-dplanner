"""Background tasks the application is running, as one observable list.

Slow work normally enters this list through ``TaskRunner`` (task_runner.py), which runs
a blocking body on a worker thread and keeps the matching Task current. The task centre
renders whatever the list holds — a bar when a fraction is known, otherwise a busy line.

Cancellation is cooperative: ``cancel()`` sets ``cancel_requested`` on the GUI thread,
the worker polls it and stops at its next safe point, and the task stays active until
its owner calls ``finish()``. Most tasks are ephemeral — gone the moment they finish.
A task started with ``keep_finished=True`` moves to the finished list instead, showing
its duration and any error, until the user dismisses it.

Estimates are remembered durations: finishing a task records how long its ``key`` took,
and the next task with the same key derives a completion fraction and a time-left guess
from it. In-memory only — a fresh session starts unestimated, which is honest.

Everything here runs on the main thread; no locks. ``cancel_requested`` is the one
field a worker thread may read (a plain bool, written only on the main thread).
"""

import time
from dataclasses import dataclass, field
from datetime import datetime

from dplanner.core.signals import Signal
from dplanner.core.telemetry import current
from dplanner.framework.user_config import get_global, set_global

# Estimate-driven fractions stop just short of full so a task that overruns its estimate
# shows as "almost there", never as falsely complete. Shared with every other surface that
# draws a remembered duration as progress (modules/sync/save_progress.py).
ESTIMATE_CAP = 0.95


@dataclass
class Task:
    task_id: int
    label: str  # What the user sees: "Saving", "Cloning wr-kofaktor…".
    key: str  # Duration-memory bucket; usually the stable operation name.
    estimate: float | None  # Seconds the last same-key task took, None the first time.
    started_at: datetime = field(default_factory=datetime.now)  # Wall clock, for display.
    monotonic_start: float = field(default_factory=time.monotonic)
    progress: float | None = None  # Explicitly reported 0..1; None → derive or spin.
    cancellable: bool = False
    cancel_requested: bool = False
    # A question the UI asks before cancelling ("Stop the copyedit of X? …"); None
    # cancels outright. Owned by the task so every Stop/Cancel surface asks the same.
    cancel_prompt: str | None = None
    keep_finished: bool = False  # Stay listed as done/failed until dismissed.
    error: str | None = None  # Set at finish when the work failed.
    timed_out: bool = False  # Set at finish when the work hit its time budget.
    duration: float | None = None  # Elapsed at finish, for "done in 32s".

    def elapsed(self) -> float:
        return time.monotonic() - self.monotonic_start

    def fraction(self) -> float | None:
        """Completion 0..1 when known (reported, or derived from the estimate)."""
        if self.progress is not None:
            return min(1.0, max(0.0, self.progress))
        if self.estimate is not None and self.estimate > 0:
            return min(ESTIMATE_CAP, self.elapsed() / self.estimate)
        return None

    def seconds_left(self) -> float | None:
        if self.progress is not None and self.progress > 0:
            return self.elapsed() * (1.0 - min(1.0, self.progress)) / self.progress
        if self.estimate is None:
            return None
        return max(0.0, self.estimate - self.elapsed())


MEMORY_ID = "tasks"
DURATIONS_KEY = "durations"


class TaskService:
    """The active and lingering-finished tasks, plus duration memory for estimates."""

    def __init__(self, *, remember: bool = False) -> None:
        """``remember`` keeps the duration memory across sessions, per user and machine.

        Off by default so a test is hermetic and a throwaway service carries no history.
        The application turns it on, because the estimate that matters most is the one for
        an operation this window has not run yet — the save at quit, in a session where
        nobody pressed Ctrl+S.
        """
        # A task started, progressed, or finished.
        self.changed: Signal[()] = Signal("tasks.changed")

        self._active: dict[int, Task] = {}
        self._finished: dict[int, Task] = {}
        self._remember = remember
        self._durations: dict[str, float] = self._recall() if remember else {}
        self._next_id = 1

    def _recall(self) -> dict[str, float]:
        stored = get_global(MEMORY_ID, DURATIONS_KEY, {})
        if not isinstance(stored, dict):
            return {}  # A hand-edited or older value is not worth a migration: start over.
        return {str(key): float(value) for key, value in stored.items()}

    def duration_of(self, key: str) -> float | None:
        """How long the last successful run under ``key`` took, if one is remembered."""
        return self._durations.get(key)

    def start(
        self,
        label: str,
        key: str | None = None,
        *,
        cancellable: bool = False,
        cancel_prompt: str | None = None,
        keep_finished: bool = False,
    ) -> Task:
        task = Task(
            task_id=self._next_id,
            label=label,
            key=key or label,
            estimate=self._durations.get(key or label),
            cancellable=cancellable,
            cancel_prompt=cancel_prompt,
            keep_finished=keep_finished,
        )
        self._next_id += 1
        self._active[task.task_id] = task
        self.changed.emit()
        return task

    def set_progress(self, task: Task, fraction: float) -> None:
        task.progress = fraction
        self.changed.emit()

    def cancel(self, task: Task) -> None:
        """Ask the task's owner to stop; the task stays active until it complies."""
        if task.task_id not in self._active or not task.cancellable or task.cancel_requested:
            return
        task.cancel_requested = True
        self.changed.emit()

    def finish(self, task: Task, error: str | None = None, *, timed_out: bool = False) -> None:
        if self._active.pop(task.task_id, None) is None:
            return
        task.duration = task.elapsed()
        task.error = error
        task.timed_out = timed_out
        current().record(
            "task",
            task.label,
            duration_ms=task.duration * 1000.0,
            error_message=error,
            key=task.key,
            timed_out=timed_out,
            cancelled=task.cancel_requested,
        )
        if error is None and not task.cancel_requested and not timed_out:
            # Cancelled, failed or timed-out runs must not poison the duration memory.
            self._durations[task.key] = task.duration
            if self._remember:
                set_global(MEMORY_ID, DURATIONS_KEY, dict(self._durations))

        if task.keep_finished:
            self._finished[task.task_id] = task
        self.changed.emit()

    def dismiss(self, task: Task) -> None:
        if self._finished.pop(task.task_id, None) is not None:
            self.changed.emit()

    def dismiss_all(self) -> None:
        if not self._finished:
            return
        self._finished.clear()
        self.changed.emit()

    def active(self) -> list[Task]:
        return list(self._active.values())

    def finished(self) -> list[Task]:
        return list(self._finished.values())
