"""The command palette: every currently-runnable action, one fuzzy search away.

Reads the same registry as the menu bar, filtered through the same context, so the palette
can never offer something the menus would refuse.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.action_registry import ActionRegistry, ActionSpec, key_sequences
from dplanner.framework.context import ContextService


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


def _plain_label(spec: ActionSpec, label: str | None) -> str:
    return (label if label is not None else spec.label).replace("&", "")


class CommandPalette(QDialog):
    def __init__(self, registry: ActionRegistry, context: ContextService, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setMinimumWidth(420)

        self._registry = registry
        self._context = context
        # Snapshot at open: the context cannot change while a modal palette is up, and a
        # stable list keeps filtering pure.
        self._entries = [
            (spec, _plain_label(spec, state.label))
            for spec, state in registry.runnable(context.current())
        ]

        self._line = QLineEdit(self)
        self._line.setObjectName("PaletteInput")
        self._line.setPlaceholderText("Type a command…")
        self._line.textChanged.connect(self._refilter)
        self._line.returnPressed.connect(self._run_selected)
        self._line.installEventFilter(self)

        self._list = QListWidget(self)
        self._list.setObjectName("PaletteList")
        self._list.itemActivated.connect(lambda _item: self._run_selected())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._line)
        layout.addWidget(self._list)

        self._refilter("")
        self._line.setFocus()

    def _refilter(self, query: str) -> None:
        scored = []
        for spec, label in self._entries:
            score = fuzzy_score(query, label)
            if score is not None:
                scored.append((-score, label, spec))
        scored.sort(key=lambda t: (t[0], t[1]))

        self._list.clear()
        for _neg_score, label, spec in scored:
            sequences = key_sequences(spec.shortcut)
            shortcut = (
                sequences[0].toString(QKeySequence.SequenceFormat.NativeText) if sequences else ""
            )
            item = QListWidgetItem(f"{label}\t{shortcut}" if shortcut else label)
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
