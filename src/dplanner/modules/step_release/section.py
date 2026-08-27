"""The Release tab: one label, committed as one undoable command."""

from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.step_release.aspect import MODULE_ID, read, write

FIELD_GAP = 6
PANEL_MARGIN = 16


class ReleaseSection(QWidget):
    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._step_id: StepId | None = None
        self._loading = False
        self.tab_visibility_changed: Signal[bool] = Signal()

        self.label = QLineEdit(self)
        self.label.setPlaceholderText("MVP, v1.0, v2…")
        self.label.editingFinished.connect(self._commit)

        note = QLabel(
            "Marks this step as a release point. When it lands is the schedule's answer;"
            " clearing the label makes it an ordinary step again.",
            self,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.label)
        layout.addWidget(note)
        layout.addStretch(1)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        return True

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self._load()

    def dispose(self) -> None:
        self._unsubscribe()

    def _load(self) -> None:
        label = ""
        if self._step_id is not None and self._product.has(self._step_id):
            label = read(self._product.step(self._step_id))
        self._loading = True
        try:
            self.label.setText(label)
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        entry = write(self.label.text())
        if entry == self._product.step(self._step_id).module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, entry, view_origin=self, label="Set Release"
            )
        )

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID:
            return
        # The echo of our own write is ignored only while the field is being edited; an undo
        # made with the panel focused still has to reach the widget.
        if origin is self and self.label.hasFocus():
            return
        self._load()
