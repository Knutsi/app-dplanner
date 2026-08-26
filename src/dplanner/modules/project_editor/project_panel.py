"""The project's own form: what the right side shows when no step is selected.

**Why this is a panel and not an aspect section.** An
:class:`~dplanner.framework.inspector.InspectorExtension`'s whole contract is
``show_target(step_id | None)`` — one target vocabulary — so making the project form a peer of
Estimate and Ticket would force every aspect editor to answer "what if this is a project?" and
hide itself, which is precisely the conditional the section registry exists to delete. As a
panel it is a peer of the *step panel* instead: two surfaces in one area, each deciding from
the context whether it has anything to show, and neither aware of the other's contents.
"""

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import NodeId, Product
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService

# DESIGN.md's side-panel spacing; the caption is the panel frame's header, not ours.
PANEL_MARGIN = 16
CAPTION_GAP = 6
FIELD_GAP = 8


class ProjectPanel(QWidget):
    """The current project's name and summary, wherever the user is looking at one."""

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self._product = product
        self._undo = undo
        self._project_id: NodeId | None = None

        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("What this project is called")
        self.title_edit.editingFinished.connect(lambda: self._commit("title"))

        self.summary_edit = QLineEdit(self)
        self.summary_edit.setPlaceholderText("What it delivers, in one line")
        self.summary_edit.editingFinished.connect(lambda: self._commit("summary"))

        fields = QFormLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(FIELD_GAP)
        fields.addRow("Name", self.title_edit)
        fields.addRow("Summary", self.summary_edit)

        hint = QLabel("Double-click the canvas to add a step.", self)
        hint.setObjectName("InspectorNote")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, 0, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)
        layout.addLayout(fields)
        layout.addSpacing(CAPTION_GAP)
        layout.addWidget(hint)
        layout.addStretch(1)

        self._unsubscribes = [product.field_changed.connect(self._on_field)]

    # -- what the context says ---------------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """The project, unless there is one step to edit — then the step panel has the area."""
        if context.selected_entity("step") is not None:
            self._project_id = None
            return False
        # focus_entity falls back from the selection to the activity's own entity, so this is
        # the same answer for the graph tab, the order table and anything opened later.
        project_id = context.focus_entity("project")
        if project_id is None or not self._product.has(project_id):
            self._project_id = None
            return False
        self._project_id = project_id
        self._refresh()
        return True

    def current_project_id(self) -> NodeId | None:
        return self._project_id

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        project = self._product.project(self._project_id) if self._project_id else None
        if project is None:
            return
        for edit, value in ((self.title_edit, project.title), (self.summary_edit, project.summary)):
            if not edit.hasFocus():
                edit.setText(value)

    def _commit(self, field_name: str) -> None:
        # editingFinished also fires during teardown, when the project may already be gone.
        if self._project_id is None or not self._product.has(self._project_id):
            return
        edit = self.title_edit if field_name == "title" else self.summary_edit
        value = edit.text().strip()
        if value != getattr(self._product.project(self._project_id), field_name):
            self._undo.push(SetFieldCommand(self._project_id, field_name, value, view_origin=self))

    def _on_field(self, node_id: NodeId, _field_name: str, origin: object) -> None:
        # Not a plain `origin is self`: an undo performed while a field has focus still has to
        # reach it, and _refresh only writes to fields that are not being typed in.
        if node_id == self._project_id and origin is not self:
            self._refresh()
