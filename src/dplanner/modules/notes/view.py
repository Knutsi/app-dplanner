"""Implementation notes: the project's log as a list, the picked note's editor beside it.

One row per note, newest first — the title over its id, label, when and where, a superseded
one muted with the note that replaced it named — in a ``RichList``: the framework's two-line
rows in the table's well, so a plan that has accumulated hundreds of handoffs costs the
window nothing to lay out. A log is one column of things, so it is a list and not a table.
Picking a row binds the editor to that note and nothing else. The strip over both carries
*Add Note…*, which records a fresh one and opens it on the title the way Step ▸ New opens
the details on the name, *Remove Note*, greyed until a note is picked, and the labels as a
filter. The *Implementation notes* tab (``activity.py``) is the page around it, and the list
follows the project after a quiet spell, like every table.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QListWidgetItem, QSplitter, QVBoxLayout, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step
from dplanner.framework.activity import follow_target
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.dictation import DictationService
from dplanner.framework.list_rows import DETAIL_ROLE, HOST_ROLE, MUTED_ROLE, RichList
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EmptyState, note
from dplanner.modules.notes.editor import NoteEditor
from dplanner.modules.notes.log import (
    DEFAULT_LABEL,
    LABELS,
    MODULE_ID,
    Note,
    next_note_id,
    read_log,
    superseded_ids,
    without_note,
    write_log,
)
from dplanner.modules.notes.reach import day
from dplanner.theme.icons import plus_icon, trash_icon
from dplanner.theme.tokens import FIELD_GAP, SECTION_GAP

NOTE_ROLE = HOST_ROLE
FRESH_TITLE = "New note"
LIST_WIDTH = 320  # Where the seam falls to begin with; the splitter keeps the proportion.
NO_NOTES = "No notes yet. `dplanner note add` records one from the terminal."
NO_MATCH = "No note carries those labels. Clear the filter to see the whole log."


def note_line(record: Note, where: str, addressed: str, superseded_by: str) -> str:
    """The row's second line: what it is, when, where, for whom, and whether it stands."""
    facts = [record.id, record.label]
    if record.made:
        facts.append(day(record.made))
    if where:
        facts.append(f"on {where}")
    if addressed:
        facts.append(f"for {addressed}")
    if superseded_by:
        facts.append(f"superseded by {superseded_by}")
    return " · ".join(facts)


class NotesView(QWidget):
    """The log beside the editor for the picked note, under the strip that adds to it."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_key: Callable[[Step], str],
        project_id: NodeId,
        debounce: DebounceService,
        parent: QWidget | None = None,
        *,
        dictation: DictationService | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._step_key = step_key
        self._project_id = project_id
        self._selected: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_GAP)
        # The verbs, then the view; the indicator outside the strip so folding never takes it.
        strip = QHBoxLayout()
        layout.addLayout(strip)  # Before it is filled: a parentless layout leaks its items.
        strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(self)
        self.add_action = self.controls.add_verb(
            "Add Note…",
            plus_icon,
            self.add_note,
            tip="Record a decision, a handoff, a spec change, something deferred",
        )
        self.remove_action = self.controls.add_verb(
            "Remove Note",
            trash_icon,
            self.remove_selected,
            tip="Drop the picked note from the log; what superseded it stands alone",
        )
        self.controls.add_divider()
        self.filter = FilterButton(label="Labels")
        for label in LABELS:
            self.filter.add_filter(label.id, label.id)
        self.controls.add_widget(self.filter)
        strip.addWidget(self.controls, 1)
        self.updating = UpdatingIndicator(self)
        strip.addWidget(self.updating)

        # What the log holds, in words that change with it.
        self.summary = note("", self)
        layout.addWidget(self.summary)

        self.split = QSplitter(Qt.Orientation.Horizontal, self)
        self.split.setChildrenCollapsible(False)
        self.list = RichList(self.split)
        self.list.currentItemChanged.connect(lambda *_args: self._on_pick())
        self.editor = NoteEditor(library, undo, step_key, self.split, dictation=dictation)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([LIST_WIDTH, LIST_WIDTH * 2])
        layout.addWidget(self.split, 1)

        # Hidden until the refresh says the log is empty; it and the split trade places, and
        # the first note has a button of its own here.
        self.empty = EmptyState(
            parent=self, action=("Add Note…", self.add_note), stands_in_for=self.split
        )
        layout.addWidget(self.empty, 1)

        # After a quiet spell, not per signal: the rows name steps, so a rename counts too.
        self._refresh_soon = Debounced(self._refresh, parent=self, service=debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            follow_target(
                library,
                lambda: self._project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.module_data_changed,
                    library.structure_changed,
                    library.field_changed,
                ),
            ),
            self.filter.changed.connect(self._refresh_soon.trigger),
        ]
        self._refresh()

    def dispose(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.editor.dispose()
        self.controls.dispose()

    # -- what the tests read -------------------------------------------------------------------

    def rows(self) -> list[tuple[str, str]]:
        """Newest first, as listed: the title and the line under it."""
        return [
            (self.list.item(index).text(), str(self.list.item(index).data(DETAIL_ROLE)))
            for index in range(self.list.count())
        ]

    def selected(self) -> str | None:
        return self._selected

    # -- verbs ---------------------------------------------------------------------------------

    def add_note(self) -> str | None:
        """Record a fresh note, then open it on the title — one undo step for the birth,
        the naming its own. Returns the new id."""
        if not self._library.has(self._project_id):
            return None
        records = read_log(self._library.project(self._project_id))
        fresh = Note(
            id=next_note_id(records),
            label=DEFAULT_LABEL,
            title=FRESH_TITLE,
            made=date.today().isoformat(),
        )
        self._selected = fresh.id  # So the refresh the push triggers lands on it.
        self._undo.push(
            SetModuleDataCommand(
                self._project_id,
                MODULE_ID,
                write_log([*records, fresh]),
                view_origin=self,
                label="Add Note",
            )
        )
        self._refresh_soon.flush()
        self.editor.title.setFocus(Qt.FocusReason.OtherFocusReason)
        self.editor.title.selectAll()
        return fresh.id

    def remove_selected(self) -> None:
        """Drop the picked note from the log — undoable; what superseded it stands alone."""
        if self._selected is None or not self._library.has(self._project_id):
            return
        records = read_log(self._library.project(self._project_id))
        if not any(record.id == self._selected for record in records):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._project_id,
                MODULE_ID,
                write_log(without_note(records, self._selected)),
                label=f"Remove Note {self._selected}",
            )
        )

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        project = (
            self._library.project(self._project_id) if self._library.has(self._project_id) else None
        )
        records = read_log(project) if project is not None else []
        replaced = {record.supersedes: record.id for record in records if record.supersedes}
        gone = superseded_ids(records)
        wanted = set(self.filter.active())
        shown = [record for record in reversed(records) if not wanted or record.label in wanted]
        self.list.blockSignals(True)
        self.list.clear()
        for record in shown:
            item = QListWidgetItem(record.title or "Untitled note")
            where = self._name(project, record.step) if record.step else ""
            addressed = ", ".join(self._name(project, step) for step in record.for_steps)
            superseded_by = replaced.get(record.id, "") if record.id in gone else ""
            item.setData(DETAIL_ROLE, note_line(record, where, addressed, superseded_by))
            item.setData(MUTED_ROLE, bool(superseded_by))
            item.setData(NOTE_ROLE, record.id)
            item.setToolTip(record.body.strip())
            self.list.addItem(item)
        rows = [
            index
            for index in range(self.list.count())
            if self.list.item(index).data(NOTE_ROLE) == self._selected
        ]
        self.list.setCurrentRow(rows[0] if rows else (0 if shown else -1))
        self.list.blockSignals(False)
        current = self.list.currentItem()
        self._selected = str(current.data(NOTE_ROLE)) if current is not None else None
        if not records:
            summary = ""
        elif wanted:
            summary = f"{len(shown)} of {len(records)} notes shown — newest first"
        else:
            standing = len(records) - len(gone)
            summary = f"{len(records)} notes, {standing} standing — newest first"
        self.summary.setText(summary)
        self.summary.setVisible(bool(summary))
        self.empty.say(NO_NOTES if not records else "" if shown else NO_MATCH)
        self._show_selected()

    def _on_pick(self) -> None:
        item = self.list.currentItem()
        self._selected = str(item.data(NOTE_ROLE)) if item is not None else None
        self._show_selected()

    def _show_selected(self) -> None:
        self.editor.show_record(self._project_id, self._selected)
        self.remove_action.setEnabled(self._selected is not None)

    def _name(self, project: Project | None, step_id: str) -> str:
        step = project.step(step_id) if project is not None else None
        return (self._step_key(step) or step.title) if step is not None else step_id
