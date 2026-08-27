"""The Handoff tab: what this step leaves behind, above what it inherits.

The top half edits — the note through the shared text stack, the scope as one undoable
command, files through the same content-addressed area the CLI writes. The bottom half only
reads: inherited material is derived on every relevant model change, rendered by the same
function the CLI prints with, and never stored.
"""

from pathlib import Path

from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.assets import attach
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import NodeId, Product, StepId, TextEdit
from dplanner.framework.cards import card_rule
from dplanner.framework.text_binding import TextBinding
from dplanner.framework.undo import UndoService
from dplanner.modules.step_handoff.aspect import MODULE_ID, read_scope, write_scope
from dplanner.modules.step_handoff.handoff import (
    FilesFor,
    asset_paths,
    inherited,
    inherited_text,
)

FIELD_GAP = 6
PANEL_MARGIN = 16
BLOCK_GAP = 12  # DESIGN.md: between blocks; FIELD_GAP is within one.

# DESIGN.md's text-well metrics: the text never touches the frame.
DOCUMENT_MARGIN = 12
LINE_HEIGHT_PERCENT = 130

NOTE_PLACEHOLDER = "What the next step's worker should know: decisions, keys, gotchas."


def _make_well(pane: QPlainTextEdit) -> None:
    pane.document().setDocumentMargin(DOCUMENT_MARGIN)


def _space_lines(pane: QPlainTextEdit) -> None:
    """~130 % line height for anything longer than a label — reapplied per setPlainText."""
    block = QTextBlockFormat()
    block.setLineHeight(
        LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor = QTextCursor(pane.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(block)


class HandoffSection(QWidget):
    def __init__(self, product: Product, undo: UndoService[Product], files: FilesFor) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._files = files
        self._step_id: StepId | None = None
        self._binding: TextBinding[Product] | None = None
        self._loading = False
        self.tab_visibility_changed: Signal[bool] = Signal()

        self.note = QPlainTextEdit(self)
        self.note.setObjectName("InspectorNotes")
        self.note.setPlaceholderText(NOTE_PLACEHOLDER)
        self.note.setFrameShape(QPlainTextEdit.Shape.NoFrame)

        self.share = QCheckBox("Share with the whole project", self)
        self.share.toggled.connect(self._commit_scope)

        # A plain button, its own width — a full-width bar would read as the surface's
        # one action, and this is not that.
        self.attach_button = QPushButton("Attach…", self)
        self.attach_button.clicked.connect(self._attach)
        attach_row = QHBoxLayout()
        attach_row.setSpacing(FIELD_GAP)
        attach_row.addWidget(self.attach_button)
        attach_row.addStretch(1)
        self.assets_label = QLabel("", self)
        self.assets_label.setObjectName("InspectorNote")
        self.assets_label.setWordWrap(True)

        inherited_caption = QLabel("Inherited", self)
        inherited_caption.setObjectName("InspectorCaption")
        self.inherited_view = QPlainTextEdit(self)
        self.inherited_view.setObjectName("InspectorNotes")
        self.inherited_view.setReadOnly(True)
        self.inherited_view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        _make_well(self.inherited_view)

        # DESIGN.md: more space between blocks (12) than within one (6), and the rule
        # that splits what-you-write from what-you-inherit gets 12 on both sides.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.note, 1)
        layout.addWidget(self.share)
        layout.addSpacing(BLOCK_GAP - FIELD_GAP)
        layout.addLayout(attach_row)
        layout.addWidget(self.assets_label)
        layout.addSpacing(BLOCK_GAP - FIELD_GAP)
        layout.addWidget(card_rule(self))
        layout.addSpacing(BLOCK_GAP - FIELD_GAP)
        layout.addWidget(inherited_caption)
        layout.addWidget(self.inherited_view, 1)

        self._unsubscribes = [
            product.module_data_changed.connect(self._on_module_data),
            product.text_edited.connect(self._on_text),
            product.edges_changed.connect(lambda *_a: self._refresh_inherited()),
        ]

    # -- the panel's side of the contract ------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        return True

    def show_target(self, target_id: str | None) -> None:
        self._close_binding()
        self._step_id = target_id if target_id and self._product.has(target_id) else None
        self.setEnabled(self._step_id is not None)
        if self._step_id is not None:
            field = ModuleTextField(self._product, self._step_id, MODULE_ID)
            self._binding = TextBinding(self.note, field, self._undo)
        else:
            self.note.setPlainText("")
        self._refresh()

    def dispose(self) -> None:
        self._close_binding()
        for unsubscribe in self._unsubscribes:
            unsubscribe()

    # -- editing -------------------------------------------------------------------------------

    def _commit_scope(self, checked: bool) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        entry = write_scope("project" if checked else "downstream")
        if entry == self._product.step(self._step_id).module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, entry, view_origin=self, label="Set Handoff Scope"
            )
        )

    def _attach(self) -> None:
        if self._step_id is None:
            return
        chosen, _filter = QFileDialog.getOpenFileName(self, "Attach to Handoff")
        if not chosen:
            return
        source = Path(chosen)
        try:
            area = self._files(self._step_id, MODULE_ID)
        except KeyError:
            # A step created moments ago has no directory until autosave flushes it.
            self.assets_label.setText("Not saved yet — try again in a moment.")
            return
        attach(area, source.read_bytes(), source.name)
        self._refresh()

    # -- reading -------------------------------------------------------------------------------

    def _refresh(self) -> None:
        self._loading = True
        try:
            scope = "downstream"
            if self._step_id is not None and self._product.has(self._step_id):
                scope = read_scope(self._product.step(self._step_id))
            self.share.setChecked(scope == "project")
        finally:
            self._loading = False
        self._refresh_assets()
        self._refresh_inherited()

    def _refresh_assets(self) -> None:
        names: tuple[str, ...] = ()
        if self._step_id is not None:
            names = asset_paths(self._files, self._step_id)
        self.assets_label.setText("\n".join(Path(name).name for name in names))
        self.assets_label.setVisible(bool(names))

    def _refresh_inherited(self) -> None:
        if self._step_id is None or not self._product.has(self._step_id):
            self.inherited_view.setPlainText("")
            return
        step = self._product.step(self._step_id)
        handoffs = inherited(self._product, step, self._files)
        self.inherited_view.setPlainText(inherited_text(handoffs))
        _make_well(self.inherited_view)
        _space_lines(self.inherited_view)

    # -- staying current -----------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if module_id != MODULE_ID:
            return
        if node_id == self._step_id and origin is not self:
            self._refresh()
            return
        # Somebody else's handoff changed; what this step inherits may have.
        self._refresh_inherited()

    def _on_text(self, edit: TextEdit, _origin: object) -> None:
        if edit.key != MODULE_ID:
            return
        if edit.node_id != self._step_id:
            self._refresh_inherited()

    def _close_binding(self) -> None:
        if self._binding is not None:
            self._binding.close()
            self._binding.setParent(None)
            self._binding = None
