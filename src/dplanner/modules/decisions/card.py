"""The project panel's Decisions card: the log as rows, and the way in to each one.

One row per decision, oldest first — what was decided over when and where — a superseded
one muted with the decision that replaced it named on its second line. Double-clicking a
row opens the decision's editor; *Add Decision…* records a fresh one and opens it on the
title, the way Step ▸ New opens the details on the name, so naming it is the gesture's
second half. Rows are reconciled by id and kept in the widget's own dict — a layout is
never read back (CLAUDE.md's crash notes). The card holds no scroller of its own; the
stack it sits in scrolls.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Step
from dplanner.domain.schedule import format_date
from dplanner.framework.undo import UndoService
from dplanner.modules.decisions.editor import DecisionDialog
from dplanner.modules.decisions.log import (
    MODULE_ID,
    Decision,
    next_decision_id,
    read_log,
    superseded_ids,
    write_log,
)

# DESIGN.md's rows of rich items.
ROW_PAD_V = 10
ROW_PAD_H = 12
LINE_GAP = 4
FRESH_TITLE = "New decision"


def _secondary(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("InspectorNote")
    label.setWordWrap(True)
    return label


class DecisionRow(QWidget):
    """What was decided, and under it when, where and whether it still stands."""

    activated = Signal(str)

    def __init__(self, decision_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.decision_id = decision_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        self.meta = _secondary("", self)
        column = QVBoxLayout(self)
        column.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        column.setSpacing(LINE_GAP)
        column.addWidget(self.title)
        column.addWidget(self.meta)

    def load(self, record: Decision, where: str, superseded_by: str) -> None:
        self.title.setText(record.title or "Untitled decision")
        # A superseded decision recedes: both lines in the secondary tone.
        self.title.setObjectName("InspectorNote" if superseded_by else "")
        facts = [record.id]
        if record.made:
            facts.append(_day(record.made))
        if where:
            facts.append(f"on {where}")
        if superseded_by:
            facts.append(f"superseded by {superseded_by}")
        self.meta.setText(" · ".join(facts))
        self.setToolTip(record.body.strip() or "Double-click to write the reasoning")

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.decision_id)
        super().mouseDoubleClickEvent(event)


def _day(made: str) -> str:
    try:
        return format_date(date.fromisoformat(made))
    except ValueError:
        return made


class DecisionsCard(QWidget):
    """The log beside the shown project, and the button that adds to it."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_key: Callable[[Step], str],
        parent_for_dialogs: QWidget | None = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._undo = undo
        self._step_key = step_key
        self._dialog_parent = parent_for_dialogs
        self._project_id: NodeId | None = None
        self._rows: dict[str, DecisionRow] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = _secondary("No decisions yet · `dplanner decision add` records one", self)
        self._layout.addWidget(self.empty)
        self.add_button = QPushButton("Add Decision…", self)
        self.add_button.setToolTip("Record a decision the project made, and why")
        self.add_button.clicked.connect(self.add_decision)
        self._layout.addSpacing(LINE_GAP * 2)
        self._layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.structure_changed.connect(lambda *_args: self._refresh()),
        ]

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._project_id = target_id
        self.setEnabled(target_id is not None)
        self._refresh()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- what the tests read -------------------------------------------------------------------

    @property
    def rows(self) -> tuple[DecisionRow, ...]:
        """Oldest first, as laid out — the dict, never the layout."""
        return tuple(self._rows.values())

    # -- verbs ---------------------------------------------------------------------------------

    def add_decision(self) -> str | None:
        """Record a fresh decision, then open it on the title — one undo step for the
        birth, the naming its own. Returns the new id."""
        if self._project_id is None or not self._library.has(self._project_id):
            return None
        records = read_log(self._library.project(self._project_id))
        fresh = Decision(
            id=next_decision_id(records), title=FRESH_TITLE, made=date.today().isoformat()
        )
        self._undo.push(
            SetModuleDataCommand(
                self._project_id,
                MODULE_ID,
                write_log([*records, fresh]),
                view_origin=self,
                label="Add Decision",
            )
        )
        self.open_editor(fresh.id)
        return fresh.id

    def open_editor(self, decision_id: str) -> None:
        if self._project_id is None or not self._library.has(self._project_id):
            return
        dialog = DecisionDialog(
            self._library,
            self._undo,
            self._step_key,
            self._project_id,
            decision_id,
            parent=self._dialog_parent or self.window(),
        )
        dialog.exec()
        dialog.dispose()
        dialog.deleteLater()

    # -- internals -----------------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if node_id == self._project_id and module_id == MODULE_ID:
            self._refresh()

    def _refresh(self) -> None:
        records: list[Decision] = []
        project = None
        if self._project_id is not None and self._library.has(self._project_id):
            project = self._library.project(self._project_id)
            records = read_log(project)
        wanted = {record.id for record in records}
        for decision_id in tuple(self._rows):
            if decision_id not in wanted:
                gone = self._rows.pop(decision_id)
                self._layout.removeWidget(gone)
                gone.hide()
                gone.deleteLater()
        replaced = {record.supersedes: record.id for record in records if record.supersedes}
        gone_ids = superseded_ids(records)
        for index, record in enumerate(records):
            row = self._rows.get(record.id)
            if row is None:
                row = DecisionRow(record.id, self)
                row.activated.connect(self.open_editor)
                self._rows[record.id] = row
            self._layout.removeWidget(row)
            self._layout.insertWidget(index, row)
            step = project.step(record.step) if project is not None and record.step else None
            where = (self._step_key(step) or step.title) if step is not None else ""
            row.load(record, where, replaced.get(record.id, "") if record.id in gone_ids else "")
        self._rows = {record.id: self._rows[record.id] for record in records}
        self.empty.setVisible(not records)
