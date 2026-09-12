"""The command palette: every currently-runnable action, one fuzzy search away.

Reads the same registry as the menu bar, filtered through the same context, so the palette
can never offer something the menus would refuse.

**A row says where the verb lives.** Two entries called *Vertical* and *Horizontal* are two
riddles; *Graph ▸ Divide ▸ Vertical* is a verb you can act on. So the row is the two-line
one every rich list here uses (``list_rows.TwoLineDelegate``): the label, the menu path
under it, the shortcut at the right, and the verb's glyph where it has one — the same
glyph the pop-up menus paint, because a palette is built fresh on every open and a colour
baked into it cannot go stale.

**And the path is searchable.** A label match still wins — typing "vertical" puts *Vertical*
first — but "divide vertical" matches through the path, which is the way somebody who
remembers the submenu and not the entry would look for it.
"""

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.action_registry import (
    PATH_SEPARATOR,
    ActionRegistry,
    ActionSpec,
    key_sequences,
)
from dplanner.framework.context import ContextService
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE, TwoLineDelegate
from dplanner.theme.icons import ICON_SIZE


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


def menu_path(spec: ActionSpec) -> str:
    """Where the verb sits in the menu bar: ``Graph ▸ Divide``, or just ``Step``.

    The group is left out on purpose — it is a module's word for a band of entries, not a
    heading anybody sees, so printing it would name something the menus never show.
    """
    return spec.menu if spec.submenu is None else spec.menu + PATH_SEPARATOR + spec.submenu


def _plain_label(spec: ActionSpec, label: str | None) -> str:
    return (label if label is not None else spec.label).replace("&", "")


class CommandPalette(QDialog):
    def __init__(self, registry: ActionRegistry, context: ContextService, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setMinimumWidth(480)

        self._registry = registry
        self._context = context
        # Snapshot at open: the context cannot change while a modal palette is up, and a
        # stable list keeps filtering pure.
        self._entries = [
            (spec, _plain_label(spec, state.label), menu_path(spec))
            for spec, state in registry.runnable(context.current())
            if spec.palette
        ]

        self._line = QLineEdit(self)
        self._line.setObjectName("PaletteInput")
        self._line.setPlaceholderText("Type a command…")
        self._line.textChanged.connect(self._refilter)
        self._line.returnPressed.connect(self._run_selected)
        self._line.installEventFilter(self)

        self._list = QListWidget(self)
        self._list.setObjectName("PaletteList")
        self._list.setItemDelegate(TwoLineDelegate(self._list))
        self._list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._list.itemActivated.connect(lambda _item: self._run_selected())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._line)
        layout.addWidget(self._list)

        self._refilter("")
        self._line.setFocus()

    def _score(self, query: str, label: str, path: str) -> tuple[int, int] | None:
        """How well the row matches, as ``(where, -score)`` — lower sorts first.

        ``where`` is 0 for a match on the label and 1 for one that needed the path, so a
        verb actually called what was typed is never pushed under one merely filed there.
        """
        direct = fuzzy_score(query, label)
        if direct is not None:
            return (0, -direct)
        through = fuzzy_score(query, f"{path}{PATH_SEPARATOR}{label}")
        return None if through is None else (1, -through)

    def _refilter(self, query: str) -> None:
        scored = []
        for spec, label, path in self._entries:
            rank = self._score(query, label, path)
            if rank is not None:
                scored.append((rank, label, path, spec))
        scored.sort(key=lambda row: (row[0], row[1]))

        ink = self.palette().color(QPalette.ColorRole.Text)
        self._list.clear()
        for _rank, label, path, spec in scored:
            sequences = key_sequences(spec.shortcut)
            item = QListWidgetItem(label)
            item.setData(DETAIL_ROLE, path)
            if sequences:
                item.setData(
                    TRAILING_ROLE,
                    sequences[0].toString(QKeySequence.SequenceFormat.NativeText),
                )
            if spec.icon is not None:
                item.setIcon(spec.icon(ink))
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _run_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:  # The stubs say non-optional; Qt returns null with no selection.
            return  # type: ignore[unreachable]
        action_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        # Run after accept so a command that opens its own dialog is not nested inside the
        # palette's modality.
        self._registry.run(action_id, self._context.current())

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        # Arrow keys move the list selection while focus stays in the line edit.
        if obj is self._line and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                delta = 1 if event.key() == Qt.Key.Key_Down else -1
                row = self._list.currentRow() + delta
                if 0 <= row < self._list.count():
                    self._list.setCurrentRow(row)
                return True
        return super().eventFilter(obj, event)
