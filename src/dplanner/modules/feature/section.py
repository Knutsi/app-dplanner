"""The Feature tab on a feature step: the record it realises, edited in place.

The same :class:`FeatureEditor` the Features panel's dialog hosts — one widget, two ways
in, so the tab and the dialog cannot drift. A step marked by the retired module names no
record; the tab says so and offers to register it, which is the Type toggle's own move.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.undo import UndoService
from dplanner.modules.feature.aspect import read
from dplanner.modules.feature.editor import FeatureEditor

# DESIGN.md: side panels get 16 px outer margins.
PANEL_MARGIN = 16
FIELD_GAP = 6


class FeatureSection(QWidget):
    """One feature step's record. ``register`` catalogues an unregistered step."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor,
        documents_of: Callable[[NodeId], list[str]],
        register: Callable[[StepId], None],
    ) -> None:
        super().__init__()
        self._library = library
        self._register = register
        self._step_id: StepId | None = None

        self.editor = FeatureEditor(library, undo, files, documents_of, self)
        self.unregistered = QWidget(self)
        column = QVBoxLayout(self.unregistered)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)
        note = QLabel(
            "This step is a feature with no record in the project's catalogue — it was "
            "marked before features had one. Register it to give it a title, a source "
            "in the spec and images.",
            self.unregistered,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        column.addWidget(note)
        self.register_button = QPushButton("Register Feature", self.unregistered)
        self.register_button.clicked.connect(self._on_register)
        column.addWidget(self.register_button)
        column.addStretch(1)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self.editor)
        self._pages.addWidget(self.unregistered)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.addWidget(self._pages)
        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)

    # -- the InspectorExtension contract ---------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self._retarget()

    def dispose(self) -> None:
        self._unsubscribe()
        self.editor.dispose()

    # -- internals -------------------------------------------------------------------------

    def _retarget(self) -> None:
        step_id = self._step_id
        if step_id is None or not self._library.has(step_id):
            self.editor.show_record(None, None)
            self._pages.setCurrentWidget(self.editor)
            return
        step = self._library.step(step_id)
        record_id = read(step)
        if not record_id:
            self.editor.show_record(None, None)
            self._pages.setCurrentWidget(self.unregistered)
            return
        self.editor.show_record(self._library.project_of(step_id).id, record_id)
        self._pages.setCurrentWidget(self.editor)

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        # The marker on the step decides which page shows; the editor follows the
        # catalogue itself.
        if node_id == self._step_id and module_id == self.editor_module_id():
            self._retarget()

    @staticmethod
    def editor_module_id() -> str:
        from dplanner.modules.feature.aspect import MODULE_ID

        return MODULE_ID

    def _on_register(self) -> None:
        if self._step_id is not None:
            self._register(self._step_id)
