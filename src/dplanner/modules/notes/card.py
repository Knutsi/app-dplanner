"""The project panel's Notes card: the log as rows, and the way in to each one.

One row per note, oldest first — the title over its id, label, when and where — a
superseded one muted with the note that replaced it named on its second line.
Double-clicking a row opens the note's editor; *Add Note…* records a fresh one and opens
it on the title, the way Step ▸ New opens the details on the name, so naming it is the
gesture's second half. Rows are reconciled by id and kept in the widget's own dict — a layout is
never read back (CLAUDE.md's crash notes). The card holds no scroller of its own; the
stack it sits in scrolls.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step
from dplanner.framework.undo import UndoService
from dplanner.modules.notes.editor import NoteDialog
from dplanner.modules.notes.log import (
    DEFAULT_LABEL,
    MODULE_ID,
    Note,
    next_note_id,
    read_log,
    superseded_ids,
    write_log,
)
from dplanner.modules.notes.reach import day

# DESIGN.md's rows of rich items.
ROW_PAD_V = 10
ROW_PAD_H = 12
LINE_GAP = 4
FRESH_TITLE = "New note"


def _secondary(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("InspectorNote")
    label.setWordWrap(True)
    return label


class NoteRow(QWidget):
    """The note's title, and under it what it is, when, where and whether it still stands."""

    activated = Signal(str)

    def __init__(self, note_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.note_id = note_id
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

    def load(self, record: Note, where: str, addressed: str, superseded_by: str) -> None:
        self.title.setText(record.title or "Untitled note")
        # A superseded note recedes: both lines in the secondary tone.
        self.title.setObjectName("InspectorNote" if superseded_by else "")
        facts = [record.id, record.label]
        if record.made:
            facts.append(day(record.made))
        if where:
            facts.append(f"on {where}")
        if addressed:
            facts.append(f"for {addressed}")
        if superseded_by:
            facts.append(f"superseded by {superseded_by}")
        self.meta.setText(" · ".join(facts))
        self.setToolTip(record.body.strip() or "Double-click to write the body")

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.note_id)
        super().mouseDoubleClickEvent(event)


class NotesCard(QWidget):
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
        self._rows: dict[str, NoteRow] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = _secondary("No notes yet · `dplanner note add` records one", self)
        self._layout.addWidget(self.empty)
        self.add_button = QPushButton("Add Note…", self)
        self.add_button.setToolTip(
            "Record a decision, a handoff, a spec change, something deferred"
        )
        self.add_button.clicked.connect(self.add_note)
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
    def rows(self) -> tuple[NoteRow, ...]:
        """Oldest first, as laid out — the dict, never the layout."""
        return tuple(self._rows.values())

    # -- verbs ---------------------------------------------------------------------------------

    def add_note(self) -> str | None:
        """Record a fresh note, then open it on the title — one undo step for the birth,
        the naming its own. Returns the new id."""
        if self._project_id is None or not self._library.has(self._project_id):
            return None
        records = read_log(self._library.project(self._project_id))
        fresh = Note(
            id=next_note_id(records),
            label=DEFAULT_LABEL,
            title=FRESH_TITLE,
            made=date.today().isoformat(),
        )
        self._undo.push(
            SetModuleDataCommand(
                self._project_id,
                MODULE_ID,
                write_log([*records, fresh]),
                view_origin=self,
                label="Add Note",
            )
        )
        self.open_editor(fresh.id)
        return fresh.id

    def open_editor(self, note_id: str) -> None:
        if self._project_id is None or not self._library.has(self._project_id):
            return
        dialog = NoteDialog(
            self._library,
            self._undo,
            self._step_key,
            self._project_id,
            note_id,
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
        records: list[Note] = []
        project = None
        if self._project_id is not None and self._library.has(self._project_id):
            project = self._library.project(self._project_id)
            records = read_log(project)
        wanted = {record.id for record in records}
        for note_id in tuple(self._rows):
            if note_id not in wanted:
                gone = self._rows.pop(note_id)
                self._layout.removeWidget(gone)
                gone.hide()
                gone.deleteLater()
        replaced = {record.supersedes: record.id for record in records if record.supersedes}
        gone_ids = superseded_ids(records)
        for index, record in enumerate(records):
            row = self._rows.get(record.id)
            if row is None:
                row = NoteRow(record.id, self)
                row.activated.connect(self.open_editor)
                self._rows[record.id] = row
            self._layout.removeWidget(row)
            self._layout.insertWidget(index, row)
            where = self._name(project, record.step) if record.step else ""
            addressed = ", ".join(self._name(project, s) for s in record.for_steps)
            replaced_by = replaced.get(record.id, "") if record.id in gone_ids else ""
            row.load(record, where, addressed, replaced_by)
        self._rows = {record.id: self._rows[record.id] for record in records}
        self.empty.setVisible(not records)

    def _name(self, project: Project | None, step_id: str) -> str:
        step = project.step(step_id) if project is not None else None
        return (self._step_key(step) or step.title) if step is not None else step_id
