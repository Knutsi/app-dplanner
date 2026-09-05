"""One decision, edited in place: what was decided, on which step, what it replaces, and
the reasoning.

Every edit is a ``SetModuleDataCommand`` over the project's log, labelled per record so
two decisions never merge into one undo step, and the widget reloads on a foreign change
with ``ModuleDataSection``'s echo rule — its own write is ignored while one of its
fields has the focus. The body is prose in a record (a string, not a ``.md``), so it goes
through ``TextBinding`` the way a feature's description does: :class:`DecisionBodyField`
describes it, and typing is undoable and coalesced for free. The dialog around it has no
buttons: every edit is already live and undoable, so Escape and the title bar close it.
"""

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
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
from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.undo import UndoService
from dplanner.modules.decisions.log import (
    MODULE_ID,
    Decision,
    read_log,
    with_decision,
    without_decision,
    write_log,
)

# DESIGN.md: dialogs 20 px out, 12 between sections, 6 within a block.
DIALOG_MARGIN = 20
BLOCK_GAP = 12
FIELD_GAP = 6
DIALOG_WIDTH = 640
DIALOG_HEIGHT = 520
BODY_PLACEHOLDER = "Why this, and what was weighed against it — the reasoning a later reader needs."


def _label(decision_id: str) -> str:
    return f"Edit Decision {decision_id}"


def _record(library: Library, project_id: NodeId, decision_id: str) -> Decision | None:
    if not library.has(project_id):
        return None
    return next((r for r in read_log(library.project(project_id)) if r.id == decision_id), None)


def _write(library: Library, project_id: NodeId, updated: Decision, origin: object) -> Command:
    records = with_decision(read_log(library.project(project_id)), updated)
    return SetModuleDataCommand(
        project_id, MODULE_ID, write_log(records), view_origin=origin, label=_label(updated.id)
    )


class DecisionBodyField:
    """A decision's reasoning, described to the framework's text binding — the feature
    description's shape: a foreign edit is reported as one replace of the whole body."""

    def __init__(self, library: Library, project_id: NodeId, decision_id: str) -> None:
        self._library = library
        self._project_id = project_id
        self._decision_id = decision_id
        self._last = self.read()

    def read(self) -> str:
        record = _record(self._library, self._project_id, self._decision_id)
        return record.body if record is not None else ""

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        record = _record(self._library, self._project_id, self._decision_id)
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


class DecisionEditor(QWidget):
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
        self._decision_id: str | None = None
        self._loading = False

        self.title = QLineEdit(self)
        self.title.setPlaceholderText("What was decided, in one line")
        self.title.editingFinished.connect(self._commit_title)

        self.step = QComboBox(self)
        self.step.setToolTip("The step this was decided on; none for a project-wide decision")
        self.step.currentIndexChanged.connect(lambda _index: self._commit_links())
        self.supersedes = QComboBox(self)
        self.supersedes.setToolTip("An earlier decision this one reverses or replaces")
        self.supersedes.currentIndexChanged.connect(lambda _index: self._commit_links())

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FIELD_GAP)
        form.addRow("Decision", self.title)
        form.addRow("On step", self.step)
        form.addRow("Supersedes", self.supersedes)

        self.body = ProseSection(
            self._field_for, undo, placeholder=BODY_PLACEHOLDER, margin=0, expand_title="Decision"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BLOCK_GAP)
        layout.addLayout(form)
        layout.addWidget(self.body, 1)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self.show_record(None, None)

    # -- what is shown ---------------------------------------------------------------------

    def show_record(self, project_id: NodeId | None, decision_id: str | None) -> None:
        if (project_id, decision_id) != (self._project_id, self._decision_id):
            self._project_id, self._decision_id = project_id, decision_id
            self.body.show_target(decision_id if project_id is not None else None)
        self.setEnabled(self.record() is not None)
        self._reload()

    def record(self) -> Decision | None:
        if self._project_id is None or self._decision_id is None:
            return None
        return _record(self._library, self._project_id, self._decision_id)

    def dispose(self) -> None:
        self._unsubscribe()
        self.body.dispose()

    # -- internals -------------------------------------------------------------------------

    def _field_for(self, decision_id: str) -> DecisionBodyField | None:
        if self._project_id is None:
            return None
        return DecisionBodyField(self._library, self._project_id, decision_id)

    def _reload(self) -> None:
        record = self.record()
        self._loading = True
        try:
            if not self.title.hasFocus():
                self.title.setText(record.title if record is not None else "")
            self._fill_steps(record)
            self._fill_supersedes(record)
        finally:
            self._loading = False

    def _fill_steps(self, record: Decision | None) -> None:
        self.step.clear()
        self.step.addItem("—", "")
        if self._project_id is None or not self._library.has(self._project_id):
            return
        for step in self._library.project(self._project_id).steps:
            key = self._step_key(step)
            self.step.addItem(f"{key}  {step.title}".strip() if key else step.title, step.id)
        if record is not None and record.step and self.step.findData(record.step) < 0:
            self.step.addItem(record.step, record.step)  # A step since deleted: still shown.
        self.step.setCurrentIndex(max(self.step.findData(record.step if record else ""), 0))

    def _fill_supersedes(self, record: Decision | None) -> None:
        self.supersedes.clear()
        self.supersedes.addItem("—", "")
        if self._project_id is None or not self._library.has(self._project_id):
            return
        for other in read_log(self._library.project(self._project_id)):
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

    def _commit_links(self) -> None:
        record = self.record()
        if self._loading or record is None:
            return
        self._push(
            replace(
                record,
                step=str(self.step.currentData() or ""),
                supersedes=str(self.supersedes.currentData() or ""),
            )
        )

    def _push(self, updated: Decision) -> None:
        if self._project_id is None or updated == self.record():
            return
        self._undo.push(_write(self._library, self._project_id, updated, self))


class DecisionDialog(QDialog):
    """One decision, front and centre, with no buttons — every edit is live and undoable.
    Remove is the one verb: it drops the record and closes. Whoever opens it owes it a
    ``dispose()``."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_key: Callable[[Step], str],
        project_id: NodeId,
        decision_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._project_id = project_id
        self._decision_id = decision_id
        self.setWindowTitle(f"Decision {decision_id}")
        self.editor = DecisionEditor(library, undo, step_key, self)
        self.editor.show_record(project_id, decision_id)

        self.remove_button = QPushButton("Remove Decision", self)
        self.remove_button.setToolTip("Drop this decision from the log — undoable")
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
        if any(record.id == self._decision_id for record in records):
            kept = [
                replace(record, supersedes="") if record.supersedes == self._decision_id else record
                for record in without_decision(records, self._decision_id)
            ]
            self._undo.push(
                SetModuleDataCommand(
                    self._project_id,
                    MODULE_ID,
                    write_log(kept),
                    label=f"Remove Decision {self._decision_id}",
                )
            )
        self.reject()
