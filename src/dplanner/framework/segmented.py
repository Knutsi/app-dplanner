"""Exclusive choices drawn as one control: the pages of a tab, a count of people.

A combo box hides the choices until it is opened, and a row of separate toggles reads as
that many verbs. A :class:`Segmented` group shows every choice at once, joined into one
shape — the quiet button's look, the picked one in the accent, the corners between
neighbours square and one hairline shared — so it reads as one question with its answer
lit. A value, not an index: the host says what each choice stands for, and hears it back.
"""

from collections.abc import Hashable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget


class Segmented(QWidget):
    """``choices`` as ``(value, label, tooltip)``; :attr:`picked` says which was chosen."""

    picked = Signal(object)

    def __init__(
        self, choices: Sequence[tuple[Hashable, str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._values: list[Hashable] = []
        self._buttons: list[QToolButton] = []
        for index, (value, label, tip) in enumerate(choices):
            button = QToolButton(self)
            button.setObjectName("ToolbarButton")
            button.setProperty("segment", _seat(index, len(choices)))
            button.setText(label)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button, index)
            row.addWidget(button)
            self._values.append(value)
            self._buttons.append(button)
        self._group.idClicked.connect(lambda index: self.picked.emit(self._values[index]))

    def value(self) -> Hashable | None:
        checked = self._group.checkedId()
        return self._values[checked] if checked >= 0 else None

    def set_value(self, value: Hashable) -> None:
        """Light the choice standing for ``value``, saying nothing — the host set it."""
        if value in self._values:
            self._buttons[self._values.index(value)].setChecked(True)

    def button(self, value: Hashable) -> QToolButton:
        return self._buttons[self._values.index(value)]


def _seat(index: int, count: int) -> str:
    """Where a choice sits in the row, for the stylesheet to square its inner corners."""
    if count == 1:
        return "only"
    if index == 0:
        return "first"
    return "last" if index == count - 1 else "middle"
