"""Task-centre module: surfaces the TaskService in the status bar and the View menu.

A status-bar button shows the running work ("Saving — 40%", "2 tasks running") or a
lingering result ("Reading through — done"); clicking it — or View ▸ Tasks… — opens the
task browser, where rows can be expanded, cancelled, and dismissed. A quarter-second
timer ticks ONLY while tasks are active, so estimate-derived fractions and elapsed times
move; an idle app has no timer running.
"""

from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.tasks import TaskService
from dplanner.framework.window import StatusHost
from dplanner.modules.taskcenter.view import TaskBrowserDialog, TaskStatusButton

TICK_MS = 250


@dataclass(frozen=True)
class TaskCenterDeps:
    tasks: TaskService
    actions: ActionRegistry
    status: StatusHost
    parent: QWidget  # The browser dialog's parent.


class TaskCenterModule:
    id = "taskcenter"

    def __init__(self, deps: TaskCenterDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        button = TaskStatusButton()
        deps.status.add_status_widget(button)
        self.button = button
        self.browser = TaskBrowserDialog(
            deps.parent, deps.tasks.cancel, deps.tasks.dismiss, deps.tasks.dismiss_all
        )

        timer = QTimer(button)
        timer.setInterval(TICK_MS)

        def refresh() -> None:
            active = deps.tasks.active()
            finished = deps.tasks.finished()
            button.show_tasks(active, finished)
            if self.browser.isVisible():
                self.browser.refresh(active + finished)
            if active and not timer.isActive():
                timer.start()
            elif not active:
                timer.stop()

        timer.timeout.connect(refresh)
        deps.tasks.changed.connect(refresh)

        def open_browser(_context: Context | None = None) -> None:
            self.browser.refresh(deps.tasks.active() + deps.tasks.finished())
            self.browser.show()  # Non-modal: the work keeps running underneath.
            self.browser.raise_()

        button.clicked.connect(lambda: open_browser())
        deps.actions.register(
            ActionSpec(
                id="taskcenter.show_tasks",
                label="&Tasks…",
                menu="View",
                group="panels",
                order=40,
                tip="Show running and finished background tasks",
                run=open_browser,
            )
        )
        refresh()
