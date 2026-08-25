"""The properties panel: where a task's plan actually lives.

Everything that makes a task a *plan* rather than a note — where it stands, who has it, how
big it is, when it runs, and what it waits on — is edited here, in one card beside the
description.

Two decisions in this file are worth reading before changing it:

**Every edit is a command.** These are not preferences; they are the plan. A status change
has to undo alongside the typing that accompanied it, so each control pushes onto the same
stack the editor uses, and each control ignores the echo of its own edit through the usual
origin check.

**A phase does not get a status.** ``Task.is_done()`` derives a parent's state from its
children, so offering an editable status on one would let a plan disagree with itself. The
control disables and says why instead of silently doing nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetDependenciesCommand, SetFieldCommand
from dplanner.domain.model import STATUSES, Plan, TaskId
from dplanner.framework.cards import card_rule
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService

MODULE_ID = "task_properties"
_ID_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class TaskPropertiesDeps:
    plan: Plan
    undo: UndoService[Plan]
    sections: InspectorSectionRegistry


class PropertiesCard(QWidget):
    """Status, assignee, estimate, dates — and what this task is waiting on."""

    def __init__(self, plan: Plan, undo: UndoService[Plan]) -> None:
        super().__init__()
        self._plan = plan
        self._undo = undo
        self._task_id: TaskId | None = None
        self._loading = False
        self.tab_visibility_changed: Signal[bool] = Signal()

        self._status = QComboBox(self)
        self._status.addItems([status.capitalize() for status in STATUSES])
        self._status.currentIndexChanged.connect(self._on_status)

        self._assignee = QLineEdit(self)
        self._assignee.setPlaceholderText("nobody yet")
        self._assignee.editingFinished.connect(self._on_assignee)

        self._estimate = QDoubleSpinBox(self)
        self._estimate.setRange(0.0, 999.0)
        self._estimate.setDecimals(1)
        self._estimate.setSingleStep(0.5)
        self._estimate.setSuffix(" d")
        # 0 reads as "not estimated", which is the honest default — an unestimated task is
        # not a zero-day task, and a plan that treats them alike understates itself.
        self._estimate.setSpecialValueText("not estimated")
        self._estimate.editingFinished.connect(self._on_estimate)

        self._start = QLineEdit(self)
        self._start.setPlaceholderText("YYYY-MM-DD")
        self._start.editingFinished.connect(lambda: self._on_date("start", self._start))
        self._due = QLineEdit(self)
        self._due.setPlaceholderText("YYYY-MM-DD")
        self._due.editingFinished.connect(lambda: self._on_date("due", self._due))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(6)
        form.addRow("Status", self._status)
        form.addRow("Assignee", self._assignee)
        form.addRow("Estimate", self._estimate)
        form.addRow("Start", self._start)
        form.addRow("Due", self._due)

        self._waiting_caption = QLabel("Waiting on", self)
        self._waiting_caption.setObjectName("InspectorCaption")
        self._waiting = QListWidget(self)
        self._waiting.setObjectName("DependencyList")
        self._waiting.setMaximumHeight(96)
        self._note = QLabel("", self)
        self._note.setObjectName("InspectorNote")
        self._note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(form)
        layout.addWidget(card_rule(self))
        layout.addWidget(self._waiting_caption)
        layout.addWidget(self._waiting)
        layout.addWidget(self._note)

        self._unsubscribes = [
            plan.field_changed.connect(self._on_model_field),
            plan.dependencies_changed.connect(self._on_model_dependencies),
            # A dependency's title or completion changes what this list should read.
            plan.title_changed.connect(lambda _id, _origin: self._show_dependencies()),
            plan.structure_changed.connect(lambda _id: self._show_dependencies()),
        ]

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        return self._task_id is not None

    def show_target(self, target_id: str | None) -> None:
        self._task_id = target_id if target_id and self._plan.has(target_id) else None
        self._reload()
        self.tab_visibility_changed.emit(self.tab_visible())

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- model → widgets -----------------------------------------------------------------------

    def _reload(self) -> None:
        self._loading = True
        try:
            if self._task_id is None:
                return
            task = self._plan.task(self._task_id)
            is_phase = task.has_children()
            index = STATUSES.index(task.status) if task.status in STATUSES else 0
            self._status.setCurrentIndex(index)
            self._status.setEnabled(not is_phase)
            self._status.setToolTip(
                "A phase is done when everything under it is" if is_phase else ""
            )
            self._assignee.setText(task.assignee)
            self._estimate.setEnabled(not is_phase)
            self._estimate.setValue(task.estimate_days or 0.0)
            if is_phase:
                self._estimate.setSpecialValueText(f"{task.rolled_up_estimate():g} d rolled up")
                self._estimate.setValue(0.0)
            else:
                self._estimate.setSpecialValueText("not estimated")
            self._start.setText(task.start)
            self._due.setText(task.due)
        finally:
            self._loading = False
        self._show_dependencies()

    def _show_dependencies(self) -> None:
        self._waiting.clear()
        if self._task_id is None or not self._plan.has(self._task_id):
            self._note.setText("")
            return
        task = self._plan.task(self._task_id)
        blocking = {other.id for other in self._plan.blockers(self._task_id)}
        for other_id in task.depends_on:
            if not self._plan.has(other_id):
                continue  # A dependency whose task was deleted; undo may bring it back.
            other = self._plan.task(other_id)
            mark = "○" if other_id in blocking else "●"
            item = QListWidgetItem(f"{mark}  {other.title or 'Untitled'}", self._waiting)
            item.setData(_ID_ROLE, other_id)
        if not task.depends_on:
            self._note.setText("Nothing. This task can start whenever.")
        elif blocking:
            self._note.setText(f"Blocked: {len(blocking)} of these are not done yet.")
        else:
            self._note.setText("Everything it waits on is done.")

    def _on_model_field(self, task_id: TaskId, _field: str, origin: object) -> None:
        if task_id == self._task_id:
            if origin is not self:
                self._reload()  # Somebody else changed this task; follow them.
            return
        # A *blocker* changed. Whether this task is still waiting depends on other tasks'
        # status, so the list has to re-read even though nothing about this one moved.
        self._show_dependencies()

    def _on_model_dependencies(self, task_id: TaskId, _origin: object) -> None:
        # Any dependency change can change this task's blocked-ness, not only its own.
        self._show_dependencies()

    # -- widgets → model -----------------------------------------------------------------------

    def _push(self, field: str, value: object) -> None:
        if self._loading or self._task_id is None:
            return
        if getattr(self._plan.task(self._task_id), field) == value:
            return
        self._undo.push(SetFieldCommand(self._task_id, field, value, view_origin=self))

    def _on_status(self, index: int) -> None:
        if 0 <= index < len(STATUSES):
            self._push("status", STATUSES[index])

    def _on_assignee(self) -> None:
        self._push("assignee", self._assignee.text().strip())

    def _on_estimate(self) -> None:
        value = self._estimate.value()
        self._push("estimate_days", None if value == 0.0 else value)

    def _on_date(self, field: str, edit: QLineEdit) -> None:
        self._push(field, edit.text().strip())

    def remove_dependency(self, other_id: TaskId) -> None:
        """Used by the Task menu's action; kept here so the command is built in one place."""
        if self._task_id is None:
            return
        remaining = [dep for dep in self._plan.task(self._task_id).depends_on if dep != other_id]
        self._undo.push(SetDependenciesCommand(self._task_id, remaining, view_origin=self))


class TaskPropertiesModule:
    id = MODULE_ID

    def __init__(self, deps: TaskPropertiesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.card",
                label="Plan",
                order=10,
                factory=lambda: PropertiesCard(deps.plan, deps.undo),
            )
        )


PropertiesFactory = Callable[[], PropertiesCard]
