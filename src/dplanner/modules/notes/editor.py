"""One note, edited in place: what it is, what it says, on which step, for whom, what it
replaces, and the body.

Every edit is a ``SetModuleDataCommand`` over the project's log, labelled per record so
two notes never merge into one undo step, and the widget reloads on a foreign change
with ``ModuleDataSection``'s echo rule — its own write is ignored while one of its
fields has the focus. The body is prose in a record (a string, not a ``.md``), so it goes
through ``TextBinding`` the way a feature's description does: :class:`NoteBodyField`
describes it, and typing is undoable and coalesced for free. The dialog around it has no
buttons: every edit is already live and undoable, so Escape and the title bar close it.
"""

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.undo import UndoService
from dplanner.framework.undo_keys import install_undo_keys
from dplanner.modules.notes.log import (
    DOWNSTREAM,
    LABELS,
    MODULE_ID,
    PROJECT,
    Note,
    label_of,
    read_log,
    with_note,
    without_note,
    write_log,
)

# DESIGN.md: dialogs 20 px out, 12 between sections, 6 within a block.
DIALOG_MARGIN = 20
BLOCK_GAP = 12
FIELD_GAP = 6
DIALOG_WIDTH = 640
DIALOG_HEIGHT = 560
BODY_PLACEHOLDER = "What a later reader needs: the reasoning, the gotcha, where things are."
FOR_PLACEHOLDER = "Step keys whose briefing carries this in full — S9 S12"


def _label(note_id: str) -> str:
    return f"Edit Note {note_id}"


def _record(library: Library, project_id: NodeId, note_id: str) -> Note | None:
    if not library.has(project_id):
        return None
    return next((r for r in read_log(library.project(project_id)) if r.id == note_id), None)


def _write(library: Library, project_id: NodeId, updated: Note, origin: object) -> Command:
    records = with_note(read_log(library.project(project_id)), updated)
    return SetModuleDataCommand(
        project_id, MODULE_ID, write_log(records), view_origin=origin, label=_label(updated.id)
    )


class NoteBodyField:
    """A note's body, described to the framework's text binding — the feature
    description's shape: a foreign edit is reported as one replace of the whole body."""

    def __init__(self, library: Library, project_id: NodeId, note_id: str) -> None:
        self._library = library
        self._project_id = project_id
        self._note_id = note_id
        self._last = self.read()

    def read(self) -> str:
        record = _record(self._library, self._project_id, self._note_id)
        return record.body if record is not None else ""

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        record = _record(self._library, self._project_id, self._note_id)
        if record is None:  # The record went while the editor was open; write nothing.
            records = read_log(self._library.project(self._project_id))
            return SetModuleDataCommand(self._project_id, MODULE_ID, write_log(records))
        body = record.body
        spliced = body[:pos] + added + body[pos + len(removed) :]
        return _write(self._library, self._project_id, replace(record, body=spliced), origin)

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_data(node_id: NodeId, module_id: str, origin: object) -> None:
            if node_id != self._project_id or module_id != MODULE_ID:
                return
            previous, current = self._last, self.read()
            self._last = current
            if previous != current:
                applied(0, previous, current, origin)

        return self._library.module_data_changed.connect(on_data)


class NoteEditor(QWidget):
    """One record's fields, each committed through the undo stack as it is left."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_key: Callable[[Step], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._step_key = step_key
        self._project_id: NodeId | None = None
        self._note_id: str | None = None
        self._loading = False

        self.label = QComboBox(self)
        for label in LABELS:
            self.label.addItem(label.id, label.id)
            tip = Qt.ItemDataRole.ToolTipRole
            self.label.setItemData(self.label.count() - 1, label.meaning, tip)
        self.label.currentIndexChanged.connect(lambda _index: self._commit_links())

        self.title = QLineEdit(self)
        self.title.setPlaceholderText("The note in one line")
        self.title.editingFinished.connect(self._commit_title)

        self.step = QComboBox(self)
        self.step.setToolTip("The step this was made on; none for a project-wide note")
        self.step.currentIndexChanged.connect(lambda _index: self._commit_links())
        self.addressed = QLineEdit(self)
        self.addressed.setPlaceholderText(FOR_PLACEHOLDER)
        self.addressed.setToolTip("Steps whose briefing carries this note in full")
        self.addressed.editingFinished.connect(self._commit_addressed)
        self.everyone = QCheckBox("Every step sees it", self)
        self.everyone.setToolTip(
            "A handoff reaches only the steps after the one it was made on; this lifts it"
            " to the whole project"
        )
        self.everyone.toggled.connect(lambda _on: self._commit_links())
        self.supersedes = QComboBox(self)
        self.supersedes.setToolTip("An earlier note this one reverses or replaces")
        self.supersedes.currentIndexChanged.connect(lambda _index: self._commit_links())

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FIELD_GAP)
        form.addRow("Label", self.label)
        form.addRow("Note", self.title)
        form.addRow("On step", self.step)
        form.addRow("For", self.addressed)
        form.addRow("", self.everyone)
        form.addRow("Supersedes", self.supersedes)

        self.body = ProseSection(
            self._field_for, undo, placeholder=BODY_PLACEHOLDER, margin=0, expand_title="Note"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BLOCK_GAP)
        layout.addLayout(form)
        layout.addWidget(self.body, 1)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self.show_record(None, None)

    # -- what is shown ---------------------------------------------------------------------

    def show_record(self, project_id: NodeId | None, note_id: str | None) -> None:
        if (project_id, note_id) != (self._project_id, self._note_id):
            self._project_id, self._note_id = project_id, note_id
            self.body.show_target(note_id if project_id is not None else None)
        self.setEnabled(self.record() is not None)
        self._reload()

    def record(self) -> Note | None:
        if self._project_id is None or self._note_id is None:
            return None
        return _record(self._library, self._project_id, self._note_id)

    def dispose(self) -> None:
        self._unsubscribe()
        self.body.dispose()

    # -- internals -------------------------------------------------------------------------

    def _field_for(self, note_id: str) -> NoteBodyField | None:
        if self._project_id is None:
            return None
        return NoteBodyField(self._library, self._project_id, note_id)

    def _project(self) -> Project | None:
        if self._project_id is None or not self._library.has(self._project_id):
            return None
        return self._library.project(self._project_id)

    def _reload(self) -> None:
        record = self.record()
        self._loading = True
        try:
            self.label.setCurrentIndex(max(self.label.findData(record.label if record else ""), 0))
            if not self.title.hasFocus():
                self.title.setText(record.title if record is not None else "")
            self._fill_steps(record)
            if not self.addressed.hasFocus():
                self.addressed.setText(self._keys(record.for_steps) if record else "")
            self._fill_reach(record)
            self._fill_supersedes(record)
        finally:
            self._loading = False

    def _keys(self, step_ids: tuple[str, ...]) -> str:
        project = self._project()
        names = []
        for step_id in step_ids:
            step = project.step(step_id) if project is not None else None
            names.append((self._step_key(step) or step.title) if step is not None else step_id)
        return " ".join(names)

    def _fill_steps(self, record: Note | None) -> None:
        self.step.clear()
        self.step.addItem("—", "")
        project = self._project()
        if project is None:
            return
        for step in project.steps:
            key = self._step_key(step)
            self.step.addItem(f"{key}  {step.title}".strip() if key else step.title, step.id)
        if record is not None and record.step and self.step.findData(record.step) < 0:
            self.step.addItem(record.step, record.step)  # A step since deleted: still shown.
        self.step.setCurrentIndex(max(self.step.findData(record.step if record else ""), 0))

    def _fill_reach(self, record: Note | None) -> None:
        # The box only means something on a note whose label reaches downstream by
        # default and that was made on a step; elsewhere it is already true.
        if record is None or not record.step or label_of(record.label).reach != DOWNSTREAM:
            self.everyone.setEnabled(False)
            self.everyone.setChecked(True)
            return
        self.everyone.setEnabled(True)
        self.everyone.setChecked(record.reach == PROJECT)

    def _fill_supersedes(self, record: Note | None) -> None:
        self.supersedes.clear()
        self.supersedes.addItem("—", "")
        project = self._project()
        if project is None:
            return
        for other in read_log(project):
            if record is None or other.id != record.id:
                self.supersedes.addItem(f"{other.id}  {other.title}", other.id)
        wanted = record.supersedes if record is not None else ""
        self.supersedes.setCurrentIndex(max(self.supersedes.findData(wanted), 0))

    def _editing(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is not None and self.isAncestorOf(focus)

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._project_id or module_id != MODULE_ID:
            return
        if origin is self and self._editing():
            return
        self.setEnabled(self.record() is not None)
        self._reload()

    def _commit_title(self) -> None:
        record = self.record()
        if self._loading or record is None:
            return
        self._push(replace(record, title=self.title.text().strip() or record.title))

    def _commit_addressed(self) -> None:
        record = self.record()
        project = self._project()
        if self._loading or record is None or project is None:
            return
        by_key = {self._step_key(step).lower(): step.id for step in project.steps}
        by_key |= {step.title.lower(): step.id for step in project.steps}
        found = [by_key.get(word.lower()) for word in self.addressed.text().split()]
        self._push(replace(record, for_steps=tuple(dict.fromkeys(f for f in found if f))))

    def _commit_links(self) -> None:
        record = self.record()
        if self._loading or record is None:
            return
        label = str(self.label.currentData() or record.label)
        step = str(self.step.currentData() or "")
        reach = ""
        if step and label_of(label).reach == DOWNSTREAM and self.everyone.isChecked():
            reach = PROJECT
        self._push(
            replace(
                record,
                label=label,
                step=step,
                reach=reach,
                supersedes=str(self.supersedes.currentData() or ""),
            )
        )

    def _push(self, updated: Note) -> None:
        if self._project_id is None or updated == self.record():
            return
        self._undo.push(_write(self._library, self._project_id, updated, self))


class NoteDialog(QDialog):
    """One note, front and centre, with no buttons — every edit is live and undoable.
    Remove is the one verb: it drops the record and closes. Whoever opens it owes it a
    ``dispose()``."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_key: Callable[[Step], str],
        project_id: NodeId,
        note_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._project_id = project_id
        self._note_id = note_id
        self.setWindowTitle(f"Note {note_id}")
        install_undo_keys(self, undo)
        self.editor = NoteEditor(library, undo, step_key, self)
        self.editor.show_record(project_id, note_id)

        self.remove_button = QPushButton("Remove Note", self)
        self.remove_button.setToolTip("Drop this note from the log — undoable")
        self.remove_button.clicked.connect(self._remove)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(BLOCK_GAP)
        layout.addWidget(self.editor, 1)
        layout.addLayout(row)
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.editor.title.setFocus(Qt.FocusReason.OtherFocusReason)
        self.editor.title.selectAll()

    def dispose(self) -> None:
        self.editor.dispose()

    def _remove(self) -> None:
        if not self._library.has(self._project_id):
            self.reject()
            return
        records = read_log(self._library.project(self._project_id))
        if any(record.id == self._note_id for record in records):
            self._undo.push(
                SetModuleDataCommand(
                    self._project_id,
                    MODULE_ID,
                    write_log(without_note(records, self._note_id)),
                    label=f"Remove Note {self._note_id}",
                )
            )
        self.reject()
