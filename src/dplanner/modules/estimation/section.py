"""The Estimate tab: how big a step is.

An :class:`~dplanner.framework.inspector.InspectorExtension` — a widget that a panel shows,
told which step to display and nothing else. It never learns which panel it is in, and the
panel never learns what an estimate is.

The input itself is :class:`~dplanner.modules.estimation.quick_input.EstimateInput`, shared
with the bulk Estimates tab; this section owns the binding to one step and the commit.
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID, read
from dplanner.modules.estimation.quick_input import EstimateInput, push_estimate

# DESIGN.md: side panels get 16 px outer margins and 6 px from a field to what belongs
# with it.
PANEL_MARGIN = 16
FIELD_GAP = 6


class EstimateSection(QWidget):
    """Days, set by hand or by chip, committed as one undoable command."""

    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._step_id: StepId | None = None

        self._input = EstimateInput(self)
        self._input.edited.connect(self._commit)
        # The tests, and anyone poking the section, reach the controls by their old names.
        self.days = self._input.days
        self.chips = self._input.chips

        note = QLabel("Working days. A week is five.", self)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self._input)
        layout.addWidget(note)
        layout.addStretch(1)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)

    # -- the panel's side of the contract ------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self._load()

    def dispose(self) -> None:
        self._unsubscribe()

    # -- internals -----------------------------------------------------------------------------

    def _load(self) -> None:
        days = None
        if self._step_id is not None and self._product.has(self._step_id):
            days = read(self._product.step(self._step_id))
        self._input.show_days(days)

    def _commit(self) -> None:
        if self._step_id is None or not self._product.has(self._step_id):
            return
        push_estimate(self._product, self._undo, self._step_id, self._input.value(), origin=self)

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID or origin is self:
            return
        self._load()
