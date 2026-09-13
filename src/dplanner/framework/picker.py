"""A fuzzy-filtered picker: a field over rich rows, and one pick.

Two surfaces want the same thing and differ only in where their rows come from — the
command palette over every runnable verb, the graph editor's *Jump to* over a project's
steps — so the field, the ranking, the two-line rows and the keyboard live here and the
rows are plain data. A third picker is a list of :class:`PickerRow`, not a third dialog.

**A label match always wins.** Typing "vertical" puts *Vertical* first; "divide vertical"
still finds it, through what the row answers to besides its name (``also`` — the menu path
for a verb, the key for a step), which is how somebody who remembers where a thing lives
rather than what it is called looks for it. A row that needed ``also`` never outranks one
whose own name matched.

The pick is reported **after** the dialog has closed, so a verb that opens a dialog of its
own is not nested inside this one's modality.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.action_registry import PATH_SEPARATOR
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE, TwoLineDelegate
from dplanner.framework.widgets import EmptyState
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import FIELD_GAP

PICKER_WIDTH = 480
NOTHING_MATCHES = "Nothing matches what was typed."


def fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match scored by contiguity; None when ``query`` is not a subsequence.

    "opit" matches "Open Item" (o-p-...-i-t). Contiguous runs score double so that
    typing an actual substring beats a scattered match.
    """
    query = query.lower()
    text = text.lower()
    if not query:
        return 0
    score = 0
    pos = -2
    for ch in query:
        found = text.find(ch, pos + 1 if pos >= 0 else 0)
        if found == -1:
            return None
        score += 2 if found == pos + 1 else 1
        pos = found
    if text.startswith(query):
        score += len(query)  # Prefix matches read as "the obvious hit"; rank them first.
    return score


@dataclass(frozen=True)
class PickerRow:
    """One row: what it is, what it is about, and what it answers to.

    ``detail`` and ``trailing`` are what the row *shows* — the second line and the note at
    the right of the first. ``also`` is what it is *searched* by when its own name does not
    match, and is deliberately separate: a shortcut shown at the right of a palette row
    would otherwise make "ctrl" match every verb that has one.

    ``landmark`` says the row is worth showing before anything is typed. When any row is
    one, an empty query lists the landmarks alone — a picker over three hundred steps
    opens on the dozen that name the plan, and everything else arrives with the first
    keystroke. A list with no landmarks opens whole, which is what the palette wants.
    """

    id: str
    label: str
    detail: str = ""
    trailing: str = ""
    icon: QIcon | None = None
    also: str = ""
    landmark: bool = False


def rank(query: str, row: PickerRow) -> tuple[int, int] | None:
    """How well ``row`` matches, as ``(where, -score)`` — lower sorts first.

    ``where`` is 0 for a match on the label and 1 for one that needed ``also``, so a row
    actually called what was typed is never pushed under one merely filed there.
    """
    direct = fuzzy_score(query, row.label)
    if direct is not None:
        return (0, -direct)
    if not row.also:
        return None
    through = fuzzy_score(query, f"{row.also}{PATH_SEPARATOR}{row.label}")
    return None if through is None else (1, -through)


class PickerDialog(QDialog):
    """A frameless modal overlay: type to filter, Enter to pick, Escape to leave."""

    def __init__(
        self,
        rows: Sequence[PickerRow],
        picked: Callable[[str], None],
        parent: QWidget,
        *,
        placeholder: str = "Type to filter…",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Picker")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setMinimumWidth(PICKER_WIDTH)

        # Snapshot at open: nothing can change under a modal, and a stable list keeps
        # filtering pure.
        self._rows = list(rows)
        self._landmarks = [row for row in self._rows if row.landmark]
        self._picked = picked

        self.field = QLineEdit(self)
        self.field.setObjectName("PickerInput")
        self.field.setPlaceholderText(placeholder)
        self.field.textChanged.connect(self._refilter)
        self.field.returnPressed.connect(self._take)
        self.field.installEventFilter(self)

        self.list = QListWidget(self)
        self.list.setObjectName("PickerList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.list.itemActivated.connect(lambda _item: self._take())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(FIELD_GAP, FIELD_GAP, FIELD_GAP, FIELD_GAP)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.field)
        layout.addWidget(self.list, 1)
        # A query that matches nothing says so where the rows would be, never an empty hole.
        self.empty = EmptyState(parent=self, stands_in_for=self.list)
        layout.addWidget(self.empty, 1)

        self._refilter("")
        self.field.setFocus()

    def _refilter(self, query: str) -> None:
        # Nothing typed: the landmarks, in the order they were given — they are the list
        # somebody scrolls, and their order is the caller's answer, not the alphabet's.
        if not query and self._landmarks:
            self._show(self._landmarks)
            return
        scored = []
        for row in self._rows:
            where = rank(query, row)
            if where is not None:
                scored.append((where, row.label, row))
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        self._show([row for _where, _label, row in scored])

    def _show(self, rows: Sequence[PickerRow]) -> None:
        self.list.clear()
        for row in rows:
            item = QListWidgetItem(row.label)
            item.setData(DETAIL_ROLE, row.detail)
            if row.trailing:
                item.setData(TRAILING_ROLE, row.trailing)
            if row.icon is not None:
                item.setIcon(row.icon)
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.empty.say("" if rows else NOTHING_MATCHES)

    def _take(self) -> None:
        item = self.list.currentItem()
        if item is None:  # The stubs say non-optional; Qt returns null with no selection.
            return  # type: ignore[unreachable]
        row_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self._picked(row_id)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        # Arrow keys move the list selection while focus stays in the line edit.
        if obj is self.field and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                delta = 1 if event.key() == Qt.Key.Key_Down else -1
                row = self.list.currentRow() + delta
                if 0 <= row < self.list.count():
                    self.list.setCurrentRow(row)
                return True
        return super().eventFilter(obj, event)
