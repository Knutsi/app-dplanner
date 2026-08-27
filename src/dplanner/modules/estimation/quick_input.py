"""The estimate input: a spin box and the quick-day chips, wherever an estimate is set.

**The chips are the fast path and the display at once.** Most steps are one of a handful of
sizes, and typing into a spin box to say "half a day" is three gestures for a value the
planner picks from a short list. The chip matching the current value reads checked, so the
row also answers "what is this set to" without reading the number.

The widget renders and reports; it never writes. Committing is :func:`push_estimate`, so
every owner — the step detail panel, a table row — pushes the same command and picks its own
``view_origin`` for echo suppression. A widget that committed for itself would fix that
origin, and the owner is the one who knows which changes are its own.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID, write

CHIP_GAP = 8

MAX_DAYS = 999.0

# The sizes a step usually is. Half a day is where most of the small work sits and the top of
# the range is where precision stops being real, so the scale opens fine and coarsens.
QUICK_DAYS = (
    (0.5, "½"),
    (1.0, "1"),
    (2.0, "2"),
    (3.0, "3"),
    (5.0, "5"),
    (10.0, "10"),
    (20.0, "20"),
)


class EstimateInput(QWidget):
    """Days, set by hand or by chip. Emits ``edited``; the owner commits."""

    def __init__(self, parent: QWidget | None = None, horizontal: bool = False) -> None:
        super().__init__(parent)
        self._loading = False
        self.edited: Signal[()] = Signal()

        self.days = QDoubleSpinBox(self)
        self.days.setRange(0.0, MAX_DAYS)
        self.days.setDecimals(1)
        self.days.setSingleStep(0.5)
        # A table row has half a pane; the panel can afford the word.
        self.days.setSuffix("d" if horizontal else " days")
        # "Not estimated" and "free" are different claims, so 0 has to be sayable as
        # neither: an empty box is unestimated, and clearing it removes the entry.
        self.days.setSpecialValueText("—")
        self.days.editingFinished.connect(self._on_edited)

        chips = QWidget(self)
        chip_row = QHBoxLayout(chips)
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(CHIP_GAP)
        # Exclusive but uncheckable-by-click: a chip says what the value is, and the way to
        # say "no estimate" is to clear the days box, not to un-press a button.
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        for value, label in QUICK_DAYS:
            chip = QPushButton(label, chips)
            chip.setObjectName("EstimateChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"{value:g} days")
            self.chips.addButton(chip, self._chip_id(value))
            chip_row.addWidget(chip)
        if not horizontal:
            chip_row.addStretch(1)
        self.chips.idClicked.connect(self._on_chip)

        layout = QHBoxLayout(self) if horizontal else QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CHIP_GAP if horizontal else 6)
        layout.addWidget(self.days)
        layout.addWidget(chips)

    def show_days(self, days: float | None) -> None:
        """Display a value without reporting it as an edit."""
        self._loading = True
        try:
            self.days.setValue(days or 0.0)
            self._show_chip(days)
        finally:
            self._loading = False

    def value(self) -> float | None:
        return self.days.value() or None

    # -- internals -----------------------------------------------------------------------------

    @staticmethod
    def _chip_id(value: float) -> int:
        """A button id per quick value. Halves exist, so the id counts half-days."""
        return int(value * 2)

    def _show_chip(self, days: float | None) -> None:
        """Check the chip for ``days``, or none of them when the value is not one of them."""
        wanted = self.chips.button(self._chip_id(days)) if days is not None else None
        self.chips.setExclusive(False)  # Exclusive groups refuse to have nothing checked.
        for button in self.chips.buttons():
            button.setChecked(button is wanted)
        self.chips.setExclusive(True)

    def _on_chip(self, chip_id: int) -> None:
        if self._loading:
            return
        self.days.setValue(chip_id / 2)
        self._on_edited()

    def _on_edited(self) -> None:
        if self._loading:
            return
        self._show_chip(self.value())
        self.edited.emit()


def push_estimate(
    product: Product,
    undo: UndoService[Product],
    step_id: StepId,
    days: float | None,
    origin: object,
) -> None:
    """The one commit path: no-op when unchanged, one undoable command otherwise."""
    entry = write(days)
    if entry == product.step(step_id).module_data.get(MODULE_ID, {}):
        return
    undo.push(
        SetModuleDataCommand(step_id, MODULE_ID, entry, view_origin=origin, label="Set Estimate")
    )
