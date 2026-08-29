"""The Estimate block on the Details tab: how big a step is.

An :class:`~dplanner.framework.inspector.InspectorExtension` — a widget that a panel shows,
told which step to display and nothing else. It never learns which panel it is in, and the
panel never learns what an estimate is.

The input itself is :class:`~dplanner.modules.estimation.quick_input.EstimateInput`, shared
with the bulk Estimates tab; this section owns the binding to one step and the commit.
"""

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import FIELD_GAP, ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID, read, write
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

        note = QLabel("Working days. A week is five.", self)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        # A compact row: the hosting Details tab owns the margins and gives the leftover
        # height to the description editor, so no stretch and no margins of its own.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self._input)
        layout.addWidget(note)

    def load_step(self, step: Step | None) -> None:
        self._input.show_days(read(step) if step is not None else None)

    def entry(self, step: Step) -> dict[str, Any]:
        return write(self._input.value())
