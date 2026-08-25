"""Task-centre widgets: the status-bar button and the task browser.

Pure widgets: the module feeds them the task lists; they only render them. Browser rows
are persistent widgets keyed by task id and reconciled on refresh — a row must survive
ticks so its expanded detail view and pressed cancel button keep their state. A row for
a ``keep_finished`` task stays after the run and switches to its finished face (outcome
line, dismiss button) in place.

Presentation follows DESIGN.md: a row states the *what* (the task label) on its primary
line and the *why* (elapsed, estimate, outcome) on a secondary line, at the rich-row
metrics; rows stack in a framed, scrolling well; the footer carries a secondary summary
and quiet buttons — nothing here is the action the user came to perform, so nothing
wears the accent.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.tasks import Task
from dplanner.framework.widgets import confirm

LEAD_WIDTH = 22  # The chevron column; kept empty on rows without detail so titles align.
LINE_GAP = 8  # Between the lead column and the text.
BAR_HEIGHT = 4


def _duration_text(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    return f"{seconds:.0f}s"


def status_text(task: Task) -> str:
    """The row's secondary line: progress while running, the outcome once finished."""
    started = f"started {task.started_at:%H:%M}"
    if task.duration is None:
        parts = [_duration_text(task.elapsed())]
        left = task.seconds_left()
        if left is not None:
            parts.append(f"about {_duration_text(left)} left")
        parts.append(started)
        return " · ".join(parts)
    took = _duration_text(task.duration)
    if task.timed_out:
        return f"Timed out after {took}"
    if task.error is not None:
        return f"Failed after {took}: {task.error}"
    if task.cancel_requested:
        return f"Cancelled after {took}"
    return f"Done in {took} · {started}"


def summary_text(running: int, finished: int) -> str:
    """The browser footer's count line; empty when there is nothing to count."""
    parts = []
    if running:
        parts.append(f"{running} running")
    if finished:
        parts.append(f"{finished} finished")
    return " · ".join(parts)


def button_text(active: list[Task], finished: list[Task]) -> str:
    """The status-bar summary: the one task's label (with % when known), else a count."""
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
    return f"{len(finished)} tasks finished"


class TaskStatusButton(QToolButton):
    """Shows running (or lingering finished) work; clicking opens the browser."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TaskStatusButton")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Background tasks — click to open")
        self.hide()

    def show_tasks(self, active: list[Task], finished: list[Task]) -> None:
        if not active and not finished:
            self.hide()
            return
        self.setText(button_text(active, finished))
        self.show()


class TaskRow(QWidget):
    """One task: title line with its actions, a status line, a progress bar while
    running, and a lazily built detail view — all indented to the title's column."""

    def __init__(
        self,
        task: Task,
        cancel: Callable[[Task], None],
        dismiss: Callable[[Task], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self._cancel_task = cancel
        self._detail: QWidget | None = None
        self.setObjectName("TaskRow")
        # A QWidget subclass paints no stylesheet border unless told to; the hairline
        # between rows is a QSS border-bottom.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(LINE_GAP)
        self.chevron: QToolButton | None = None
        if task.detail_factory is not None:
            chevron = QToolButton(self)
            chevron.setArrowType(Qt.ArrowType.RightArrow)
            chevron.setAutoRaise(True)
            chevron.setFixedWidth(LEAD_WIDTH)
            chevron.setToolTip("Details")
            chevron.clicked.connect(self._toggle_detail)
            title_line.addWidget(chevron)
            self.chevron = chevron
        else:
            lead = QWidget(self)
            lead.setFixedWidth(LEAD_WIDTH)
            title_line.addWidget(lead)
        self.title = QLabel(task.label, self)
        self.title.setWordWrap(True)
        title_line.addWidget(self.title, 1)
        self.cancel_button: QToolButton | None = None
        if task.cancellable:
            button = QToolButton(self)
            button.setObjectName("TaskRowCancel")
            button.setText("Cancel")
            button.clicked.connect(self._cancel)
            title_line.addWidget(button)
            self.cancel_button = button
        self.dismiss_button: QToolButton | None = None
        if task.keep_finished:
            button = QToolButton(self)
            button.setObjectName("TaskRowDismiss")
            button.setText("✕")
            button.setAutoRaise(True)
            button.setToolTip("Dismiss")
            button.clicked.connect(lambda: dismiss(self.task))
            button.hide()  # Only a finished row can be dismissed.
            self.dismiss_button = button
            title_line.addWidget(button)

        self.status = QLabel(self)
        self.status.setObjectName("TaskRowStatus")
        self.status.setWordWrap(True)
        self.bar = QProgressBar(self)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(BAR_HEIGHT)

        # Everything under the title sits in the title's column, clear of the chevron.
        self._below = QVBoxLayout()
        self._below.setContentsMargins(LEAD_WIDTH + LINE_GAP, 0, 0, 0)
        self._below.setSpacing(4)
        self._below.addWidget(self.status)
        self._below.addWidget(self.bar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)  # Rich-row metrics per DESIGN.md.
        layout.setSpacing(4)
        layout.addLayout(title_line)
        layout.addLayout(self._below)
        self.refresh()

    def _cancel(self) -> None:
        prompt = self.task.cancel_prompt
        if prompt is None or confirm(self, "Stop Task", prompt):
            self._cancel_task(self.task)

    def _toggle_detail(self) -> None:
        assert self.chevron is not None and self.task.detail_factory is not None
        if self._detail is None:
            self._detail = self.task.detail_factory()
            self._below.addWidget(self._detail)
        else:
            self._detail.setVisible(not self._detail.isVisible())
        expanded = self._detail.isVisible()
        self.chevron.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def refresh(self) -> None:
        task = self.task
        self.status.setText(status_text(task))
        if task.duration is not None:  # Finished (only keep_finished rows linger).
            self.bar.hide()
            if self.cancel_button is not None:
                self.cancel_button.hide()
            if self.dismiss_button is not None:
                self.dismiss_button.show()
            return
        fraction = task.fraction()
        if fraction is None:
            if self.bar.maximum() != 0:
                self.bar.setRange(0, 0)  # Qt's animated indeterminate state.
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(fraction * 100))
        if (
            self.cancel_button is not None
            and task.cancel_requested
            and self.cancel_button.isEnabled()
        ):
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Stopping…")


class TaskBrowserDialog(QDialog):
    """Running and lingering-finished tasks as persistent rows, reconciled by task id."""

    def __init__(
        self,
        parent: QWidget | None,
        cancel: Callable[[Task], None],
        dismiss: Callable[[Task], None],
        clear_all: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TaskBrowserDialog")
        self.setWindowTitle("Tasks")
        self.setMinimumSize(440, 300)
        self.resize(520, 380)
        self._cancel = cancel
        self._dismiss = dismiss
        self._rows: dict[int, TaskRow] = {}

        # Rows occupy indices 0..n-1; the stretches centre the empty label when none.
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)  # Rows carry their own padding and hairline.
        self.empty = QLabel("No tasks running.")
        self.empty.setObjectName("TaskBrowserEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows_layout.addStretch(1)
        self._rows_layout.addWidget(self.empty)
        self._rows_layout.addStretch(1)

        self.well = QScrollArea(self)
        self.well.setObjectName("TaskBrowserWell")
        self.well.setWidgetResizable(True)
        self.well.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.well.setWidget(self._rows_host)
        # setWidget() switches the host's autofill on, which would paint an opaque slab
        # over the well's themed surface.
        self._rows_host.setAutoFillBackground(False)

        self.summary = QLabel(self)
        self.summary.setObjectName("TaskBrowserSummary")
        self.clear_button = QPushButton("Clear finished", self)
        self.clear_button.clicked.connect(lambda: clear_all())
        self.clear_button.hide()  # Only shown while finished rows linger.
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        # Without an explicit default Qt promotes the first auto-default button — Clear
        # finished — and Enter would silently clear tasks.
        self.close_button.setDefault(True)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.summary)
        footer.addStretch(1)
        footer.addWidget(self.clear_button)
        footer.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)  # Dialog metrics per DESIGN.md.
        layout.setSpacing(12)
        layout.addWidget(self.well, 1)
        layout.addLayout(footer)

    def refresh(self, tasks: list[Task]) -> None:
        wanted = {task.task_id for task in tasks}
        for task_id, row in list(self._rows.items()):
            if task_id not in wanted:
                self._rows_layout.removeWidget(row)
                row.hide()  # Gone now, not at the next deferred-delete pass.
                row.deleteLater()
                del self._rows[task_id]
        for task in tasks:
            existing = self._rows.get(task.task_id)
            if existing is None:
                new_row = TaskRow(task, self._cancel, self._dismiss, self._rows_host)
                self._rows_layout.insertWidget(len(self._rows), new_row)
                self._rows[task.task_id] = new_row
            else:
                existing.refresh()
        running = sum(1 for task in tasks if task.duration is None)
        finished = len(tasks) - running
        self.summary.setText(summary_text(running, finished))
        self.empty.setVisible(not tasks)
        self.clear_button.setVisible(finished > 0)
