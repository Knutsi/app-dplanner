"""The estimate input: a spin box and the quick-day chips, wherever an estimate is set.

**The chips are the fast path and the display at once.** Most steps are one of a handful of
sizes, and typing into a spin box to say "half a day" is three gestures for a value the
planner picks from a short list. The chip matching the current value reads checked, so the
row also answers "what is this set to" without reading the number.

**Zero is a claim, and it has its own chip.** "Not estimated" and "adds no time" are
different things to say about a step — the first is missing, the second is counted — so
the box has to show both: its minimum is one step *under* zero and prints as a dash, and
0 prints as 0. *Does not add time* stands apart from the sizes, past a rule, because it
is not a size.

The widget renders and reports; it never writes. Committing is :func:`push_estimate`, so
every owner — the step detail panel, a table row — pushes the same command and picks its own
``view_origin`` for echo suppression. A widget that committed for itself would fix that
origin, and the owner is the one who knows which changes are its own.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, StepId
from dplanner.framework.cards import card_rule
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import NumberBox
from dplanner.modules.estimation.aspect import MODULE_ID, write

CHIP_GAP = 8

MAX_DAYS = 999.0
# The finest estimate — one agent task — and the box's step. One step under zero is the
# box's "no estimate": the special value text prints it as a dash, an arrow-down from 0
# reaches it, and 0 itself stays sayable.
QUARTER = 0.25
UNESTIMATED = -QUARTER

FREE_LABEL = "Does not add time"
FREE_TIP = "0 days — counted as estimated, and adds no time to the plan"
QUARTER_TIP = "0.25 days — one agent task, about two hours with a human in the loop"

# The sizes a step usually is. A quarter day is one agent task (about two hours with a
# human in the loop), half a day is where most small human work sits, and the top of the
# range is where precision stops being real, so the scale opens fine and coarsens.
QUICK_DAYS = (
    (0.25, "¼"),
    (0.5, "½"),
    (1.0, "1"),
    (2.0, "2"),
    (3.0, "3"),
    (5.0, "5"),
    (10.0, "10"),
    (20.0, "20"),
)


def size_tip(days: float) -> str:
    """What a quick size means, in the words its chip's tooltip says wherever it is offered."""
    return QUARTER_TIP if days == QUARTER else f"{days:g} days"


class EstimateInput(QWidget):
    """Days, set by hand or by chip. Emits ``edited``; the owner commits."""

    def __init__(self, parent: QWidget | None = None, horizontal: bool = False) -> None:
        super().__init__(parent)
        self._loading = False
        self.edited: Signal[()] = Signal()

        self.days = NumberBox(self)
        self.days.setRange(UNESTIMATED, MAX_DAYS)
        self.days.setDecimals(2)
        self.days.setSingleStep(QUARTER)
        # A table row has half a pane; the panel can afford the word.
        self.days.setSuffix("d" if horizontal else " days")
        # The minimum is "not estimated", printed as a dash; stepping down to it removes
        # the entry. 0 is above it, and means what it says.
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
            chip_row.addWidget(self._chip(chips, value, label, size_tip(value)))
        # Zero is not a size: it stands past a rule, worded as the claim it makes.
        chip_row.addWidget(card_rule(chips, vertical=True))
        self.free = self._chip(chips, 0.0, FREE_LABEL, FREE_TIP)
        chip_row.addWidget(self.free)
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
            self.days.setValue(UNESTIMATED if days is None else days)
            self._show_chip(days)
        finally:
            self._loading = False

    def value(self) -> float | None:
        """The days shown, or None at the box's dash — 0 is a value."""
        shown = self.days.value()
        return None if shown < 0 else shown

    # -- internals -----------------------------------------------------------------------------

    def _chip(self, parent: QWidget, value: float, label: str, tip: str) -> QPushButton:
        chip = QPushButton(label, parent)
        chip.setObjectName("EstimateChip")
        chip.setCheckable(True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip(tip)
        self.chips.addButton(chip, self._chip_id(value))
        return chip

    @staticmethod
    def _chip_id(value: float) -> int:
        """A button id per quick value. Quarters exist, so the id counts quarter-days —
        and 0, a legal id, is the chip that adds no time."""
        return int(value * 4)

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
        self.days.setValue(chip_id * QUARTER)
        self._on_edited()

    def _on_edited(self) -> None:
        if self._loading:
            return
        self._show_chip(self.value())
        self.edited.emit()


def push_estimate(
    library: Library,
    undo: UndoService[Library],
    step_id: StepId,
    days: float | None,
    origin: object,
) -> None:
    """One step at one size: :func:`push_estimates` over a single step."""
    push_estimates(library, undo, (step_id,), days, origin)


def push_estimates(
    library: Library,
    undo: UndoService[Library],
    step_ids: Sequence[StepId],
    days: float | None,
    origin: object = None,
) -> None:
    """The one commit path: every step at one size, as one undo entry however many there
    are, and nothing at all for the steps already at it."""
    commands: list[Command] = []
    for step_id in step_ids:
        previous = library.step(step_id).module_data.get(MODULE_ID, {})
        entry = write(days, previous=previous)
        if entry != previous:
            commands.append(
                SetModuleDataCommand(
                    step_id, MODULE_ID, entry, view_origin=origin, label="Set Estimate"
                )
            )
    if commands:
        undo.push(commands[0] if len(commands) == 1 else CompositeCommand("Set Estimate", commands))
