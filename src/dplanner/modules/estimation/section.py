"""The Estimate tab: how big a step is.

An :class:`~dplanner.framework.inspector.InspectorExtension` — a widget that a panel shows,
told which step to display and nothing else. It never learns which panel it is in, and the
panel never learns what an estimate is.

**The chips are the fast path and the display at once.** Most steps are one of a handful of
sizes, and typing into a spin box to say "half a day" is three gestures for a value the
planner picks from a short list. The chip matching the current value reads checked, so the
row also answers "what is this set to" without reading the number.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID, read, write

# DESIGN.md: side panels get 16 px outer margins, 12 px between blocks and 6 px from a field
# to what belongs with it.
PANEL_MARGIN = 16
FIELD_GAP = 6
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


class EstimateSection(QWidget):
    """Days, set by hand or by chip, committed as one undoable command."""

    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._step_id: StepId | None = None
        self._loading = False
        self.tab_visibility_changed: Signal[bool] = Signal()

        self.days = QDoubleSpinBox(self)
        self.days.setRange(0.0, MAX_DAYS)
        self.days.setDecimals(1)
        self.days.setSingleStep(0.5)
        self.days.setSuffix(" days")
        # "Not estimated" and "free" are different claims, so 0 has to be sayable as
        # neither: an empty box is unestimated, and clearing it removes the entry.
        self.days.setSpecialValueText("—")
        self.days.editingFinished.connect(self._commit)

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
        chip_row.addStretch(1)
        self.chips.idClicked.connect(self._on_chip)

        note = QLabel("Working days. A week is five.", self)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.days)
        layout.addWidget(chips)
        layout.addWidget(note)
        layout.addStretch(1)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)

    # -- the panel's side of the contract ------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        # Always, once there is a step: a tab that hid itself when the value was empty
        # would be a tab you could never use to set one.
        return True

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self._load()

    def dispose(self) -> None:
        self._unsubscribe()

    # -- internals -----------------------------------------------------------------------------

    @staticmethod
    def _chip_id(value: float) -> int:
        """A button id per quick value. Halves exist, so the id counts half-days."""
        return int(value * 2)

    def _load(self) -> None:
        days = None
        if self._step_id is not None and self._product.has(self._step_id):
            days = read(self._product.step(self._step_id))
        self._loading = True
        try:
            self.days.setValue(days or 0.0)
            self._show_chip(days)
        finally:
            self._loading = False

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
        self._commit()

    def _commit(self) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        days = self.days.value() or None
        self._show_chip(days)
        entry = write(days)
        if entry == self._product.step(self._step_id).module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, entry, view_origin=self, label="Set Estimate"
            )
        )

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID or origin is self:
            return
        self._load()
