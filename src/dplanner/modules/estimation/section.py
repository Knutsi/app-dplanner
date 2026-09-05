"""The Estimate block on the Details tab: how big a step is.

An :class:`~dplanner.framework.inspector.InspectorExtension` — a widget that a panel shows,
told which step to display and nothing else. It never learns which panel it is in, and the
panel never learns what an estimate is.

The input itself is :class:`~dplanner.modules.estimation.quick_input.EstimateInput`, shared
with the bulk Estimates tab; this section owns the binding to one step and the commit.
"""

from typing import Any

from PySide6.QtWidgets import QVBoxLayout

from dplanner.domain.model import Library, Step
from dplanner.domain.schedule import format_date
from dplanner.framework.module_data_section import FIELD_GAP, ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID, read, read_history, write
from dplanner.modules.estimation.quick_input import EstimateInput


class EstimateSection(ModuleDataSection):
    """Days, set by hand or by chip, committed as one undoable command."""

    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Estimate")

        self._input = EstimateInput(self)
        self._input.edited.connect(self.commit)
        # The tests, and anyone poking the section, reach the controls by their old names.
        self.days = self._input.days
        self.chips = self._input.chips

        # A compact row: the hosting Details tab owns the margins and gives the leftover
        # height to the description editor, so no stretch and no margins of its own.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self._input)

    def load_step(self, step: Step | None) -> None:
        self._input.show_days(read(step) if step is not None else None)
        # What the estimate was before, on the field itself: a review reads it by hovering.
        history = read_history(step) if step is not None else []
        self.days.setToolTip(
            "\n".join(f"was {was:g}d until {format_date(when)}" for when, was in history)
        )

    def entry(self, step: Step) -> dict[str, Any]:
        return write(self._input.value(), previous=step.module_data.get(MODULE_ID))
