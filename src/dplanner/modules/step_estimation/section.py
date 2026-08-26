"""The Estimate tab: how big a step is, and how sure we are.

An :class:`~dplanner.framework.inspector.InspectorExtension` — a widget that a panel shows,
told which step to display and nothing else. It never learns which panel it is in, and the
panel never learns what an estimate is.
"""

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.step_estimation.aspect import CONFIDENCES, MODULE_ID, Estimate, read, write

FORM_SPACING = 8
PANEL_MARGIN = 16
MAX_DAYS = 999.0


class EstimateSection(QWidget):
    """Days and confidence, committed as one undoable command."""

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
        # "Not estimated" and "free" are different claims, so 0 has to be sayable as
        # neither: an empty box is unestimated, and clearing it removes the entry.
        self.days.setSpecialValueText("—")
        self.days.editingFinished.connect(self._commit)

        self.confidence = QComboBox(self)
        self.confidence.addItem("—", "")
        for level in CONFIDENCES:
            self.confidence.addItem(level.title(), level)
        self.confidence.currentIndexChanged.connect(self._commit)

        layout = QFormLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FORM_SPACING)
        layout.addRow("Days", self.days)
        layout.addRow("Confidence", self.confidence)

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

    def _load(self) -> None:
        estimate = None
        if self._step_id is not None and self._product.has(self._step_id):
            estimate = read(self._product.step(self._step_id))
        self._loading = True
        try:
            self.days.setValue(estimate.days if estimate else 0.0)
            wanted = estimate.confidence if estimate else ""
            self.confidence.setCurrentIndex(max(0, self.confidence.findData(wanted)))
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        days = self.days.value()
        confidence = str(self.confidence.currentData() or "")
        estimate = None if days <= 0.0 else Estimate(days=days, confidence=confidence)
        entry = write(estimate)
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
