"""Task-centre widgets: the status-bar words and the task browser.

Pure widgets: the module feeds them the task lists; they only render them. The browser is a
``DialogFrame`` over a ``RowWell``: rows are kept by task id across every tick, so a pressed
Cancel keeps its state, and a ``keep_finished`` task's row turns to its outcome in place.

A row says *what* on its first line — the task's label — and how it stands on a status line
whose tone is the mood: busy while it runs, ok once it is done, the error tone when it failed
or timed out. Under the line sits a 4 px bar only while the end is known, filled by what the
task reported or by how long the same work took last time: an unknown fraction is busy, and
the line already says busy. Every edit here is live, so the footer is Close, a secondary
that clears what has finished, and nothing that wears the accent.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QPushButton, QToolButton, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.signalling import Tone
from dplanner.framework.tasks import Task
from dplanner.framework.widgets import EmptyState, confirm

BROWSER_SIZE = (520, 380)
NO_TASKS = "No tasks running."


def _duration_text(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    return f"{seconds:.0f}s"


def status_of(task: Task) -> tuple[str, Tone]:
    """The row's status line and its tone: progress while running, the outcome once finished."""
    started = f"started {task.started_at:%H:%M}"
    if task.duration is None:
        parts = [_duration_text(task.elapsed())]
        left = task.seconds_left()
        if left is not None:
            parts.append(f"about {_duration_text(left)} left")
        parts.append(started)
        return " · ".join(parts), "busy"
    took = _duration_text(task.duration)
    if task.timed_out:
        return f"Timed out after {took}", "error"
    if task.error is not None:
        return f"Failed after {took}: {task.error}", "error"
    if task.cancel_requested:
        return f"Cancelled after {took}", "info"
    return f"Done in {took} · {started}", "ok"


def summary_text(running: int, finished: int) -> str:
    """The browser footer's count line; empty when there is nothing to count."""
    parts = []
    if running:
        parts.append(f"{running} running")
    if finished:
        parts.append(f"{finished} finished")
    return " · ".join(parts)


def button_text(active: list[Task], finished: list[Task]) -> str:
    """The status-bar words: the one task's label (with % when known), else a count, else
    nothing — a status bar with no work in it says nothing."""
    if len(active) == 1:
        task = active[0]
        fraction = task.fraction()
        if fraction is not None:
            return f"{task.label} — {fraction:.0%}"
        return f"{task.label}…"
    if active:
        return f"{len(active)} tasks running"
    if len(finished) == 1:
        task = finished[0]
        outcome = "timed out" if task.timed_out else "failed" if task.error else "done"
        return f"{task.label} — {outcome}"
    return f"{len(finished)} tasks finished" if finished else ""


class TaskRow(WellRow):
    """One task: its label with Cancel and the dismissal, its status line, its bar."""

    def __init__(
        self, task: Task, cancel: Callable[[Task], None], dismiss: Callable[[Task], None]
    ) -> None:
        super().__init__(task.label)
        self.task = task
        self._cancel_task = cancel
        self.cancel_button: QToolButton | None = None
        if task.cancellable:
            self.cancel_button = self.add_button("Cancel", self._cancel, tip="Stop this task")
        self.dismiss_button: QToolButton | None = None
        if task.keep_finished:
            self.dismiss_button = self.add_dismiss(lambda: dismiss(self.task))
            self.dismiss_button.hide()  # Only a finished row can be dismissed.
        self.refresh()

    def _cancel(self) -> None:
        prompt = self.task.cancel_prompt
        if prompt is None or confirm(self, "Stop Task", prompt, verb="Stop"):
            self._cancel_task(self.task)

    def refresh(self) -> None:
        task = self.task
        self.status.say(*status_of(task))
        if task.duration is not None:  # Finished: only a keep_finished row lingers.
            self.show_fraction(None)
            if self.cancel_button is not None:
                self.cancel_button.hide()
            if self.dismiss_button is not None:
                self.dismiss_button.show()
            return
        self.show_fraction(task.fraction())
        cancel = self.cancel_button
        if cancel is not None and task.cancel_requested and cancel.isEnabled():
            cancel.setEnabled(False)
            cancel.setText("Stopping…")


class TaskBrowserDialog(DialogFrame):
    """Running and lingering-finished tasks as rows kept by task id."""

    def __init__(
        self,
        parent: QWidget | None,
        cancel: Callable[[Task], None],
        dismiss: Callable[[Task], None],
        clear_all: Callable[[], None],
    ) -> None:
        super().__init__("Tasks", parent, size=BROWSER_SIZE)
        self.setObjectName("TaskBrowserDialog")
        # Not ``_dismiss``: the frame keeps its own way out under that name.
        self._cancel_task = cancel
        self._dismiss_task = dismiss
        self.well = RowWell(self.body)
        self.body_layout.addWidget(self.well, 1)
        self.empty = EmptyState(NO_TASKS, self.body, stands_in_for=self.well)
        self.body_layout.addWidget(self.empty, 1)
        self.clear_button: QPushButton = self.add_button("Clear finished", clear_all)
        self.clear_button.setEnabled(False)  # Disabled, never hidden: nothing has finished.
        self.close_button = self.add_dismiss("Close")

    def rows(self) -> list[TaskRow]:
        """The listed tasks' rows, top to bottom."""
        return [row for row in self.well.rows() if isinstance(row, TaskRow)]

    def refresh(self, tasks: list[Task]) -> None:
        by_id = {task.task_id: task for task in tasks}
        self.well.reconcile(
            list(by_id),
            lambda task_id: TaskRow(by_id[task_id], self._cancel_task, self._dismiss_task),
            lambda _task_id, row: row.refresh(),
        )
        running = sum(1 for task in tasks if task.duration is None)
        finished = len(tasks) - running
        self.status.say(summary_text(running, finished))
        self.empty.say("" if tasks else NO_TASKS)
        self.clear_button.setEnabled(finished > 0)
