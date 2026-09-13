"""The Feature tab: the spec passages this feature was read from.

Everything else a feature used to carry is the step's now — its name is the step's title
and its prose the step's description, both edited in the Details tab — so what is left
here is the one fact nothing else can hold: where in a specification this feature came
from. *One editor per fact.*

**Passages are a list with one set of fields.** A feature is routinely read from two
places in a spec, so the block is a short list of them — document and page on the first
line, the quote's first line under it — and the same three fields edit whichever row is
picked; Add appends a blank row and picks it, Remove drops the picked one. A row whose
document or quote changes is re-stamped with the document's digest through ``digest_of``,
handed in by the composition root so this widget never learns how a spec is stored.

Every change is a ``SetModuleDataCommand`` over the step's own entry, and the widget
reloads on a foreign change with the same echo rule ``ModuleDataSection`` uses: its own
write is ignored while one of its fields has the focus.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.list_rows import DETAIL_ROLE, TwoLineDelegate
from dplanner.framework.undo import UndoService
from dplanner.modules.feature.aspect import MODULE_ID, FeatureSource, read, write
from dplanner.theme.icons import plus_icon, trash_icon
from dplanner.theme.tokens import PANEL_MARGIN

# DESIGN.md: within a block.
FIELD_GAP = 6
QUOTE_LINES = 4
PASSAGE_ROWS = 3  # The list shows this many passages before it scrolls.

# (project id, document name) → the document's digest now, "" when it is unknown.
type DigestOf = Callable[[NodeId, str], str]


def passage_title(source: FeatureSource) -> str:
    page = f" p.{source.page}" if source.page is not None else ""
    return f"{source.document or '(no document)'}{page}"


def passage_detail(source: FeatureSource) -> str:
    first = source.quote.strip().splitlines()
    return first[0] if first else "the whole document"


class _QuoteEdit(QPlainTextEdit):
    """A few lines of quoted spec, committed when the focus leaves — a line edit's
    ``editingFinished`` for a field that may wrap."""

    editing_finished = Signal()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self.editing_finished.emit()


def _glyph_button(parent: QWidget, tip: str) -> QToolButton:
    """The quiet glyph button: the label is the tooltip."""
    button = QToolButton(parent)
    button.setObjectName("ToolbarButton")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button.setToolTip(tip)
    return button


class FeatureEditor(QWidget):
    """One feature step's passages, committed through the undo stack as each is left.

    It is the ``InspectorExtension`` itself — there is no page to swap to any more, since
    a feature step is always a whole feature and there is nothing left to register.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        documents_of: Callable[[NodeId], list[str]] | None = None,
        parent: QWidget | None = None,
        *,
        digest_of: DigestOf | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._documents_of = documents_of
        self._digest_of = digest_of
        self._step_id: StepId | None = None
        self._loading = False

        self.passages = QListWidget(self)
        self.passages.setItemDelegate(TwoLineDelegate(self.passages))
        self.passages.setFixedHeight(self.passages.fontMetrics().height() * 2 * PASSAGE_ROWS + 24)
        self.passages.currentRowChanged.connect(lambda _row: self._show_passage())
        self.add_passage = _glyph_button(self, "Add a passage")
        self.add_passage.clicked.connect(self._add_passage)
        self.remove_passage = _glyph_button(self, "Remove this passage")
        self.remove_passage.clicked.connect(self._remove_passage)
        passages_row = QHBoxLayout()
        passages_row.setSpacing(FIELD_GAP)
        passages_row.addWidget(QLabel("Read from", self))
        passages_row.addStretch(1)
        passages_row.addWidget(self.add_passage)
        passages_row.addWidget(self.remove_passage)

        self.document = QComboBox(self)
        self.document.currentIndexChanged.connect(lambda _index: self._commit_passage())
        self.page = QSpinBox(self)
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("—")
        self.page.valueChanged.connect(lambda _value: self._commit_passage())
        self.quote = _QuoteEdit(self)
        self.quote.setPlaceholderText("The passage it was read from")
        self.quote.setFixedHeight(self.quote.fontMetrics().height() * QUOTE_LINES + 12)
        self.quote.editing_finished.connect(self._commit_passage)
        source_row = QHBoxLayout()
        source_row.setSpacing(FIELD_GAP)
        source_row.addWidget(self.document, 1)
        source_row.addWidget(QLabel("page", self))
        source_row.addWidget(self.page)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FIELD_GAP)
        form.addRow(passages_row)
        form.addRow(self.passages)
        form.addRow("From", source_row)
        form.addRow("Quote", self.quote)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addLayout(form)
        layout.addStretch(1)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self._paint_icons()
        self.show_target(None)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(self.cites() is not None)
        self._reload()

    def focus_entity(self, kind: str, entity_id: str) -> bool:
        """The Feature tab answers for its own step — a feature *is* a step now."""
        return kind == "feature" and entity_id == self._step_id

    def dispose(self) -> None:
        self._unsubscribe()

    # -- what is shown -------------------------------------------------------------------------

    def cites(self) -> tuple[FeatureSource, ...] | None:
        """The passages shown, or None when the target is not a feature step."""
        if self._step_id is None or not self._library.has(self._step_id):
            return None
        return read(self._library.step(self._step_id))

    def select_passage(self, index: int) -> None:
        """Pick a passage by its position — what a jump from the spec lands on."""
        if 0 <= index < self.passages.count():
            self.passages.setCurrentRow(index)

    # -- internals -----------------------------------------------------------------------------

    def _paint_icons(self) -> None:
        colour = self.palette().text().color()
        self.add_passage.setIcon(plus_icon(colour))
        self.remove_passage.setIcon(trash_icon(colour.name()))

    def _reload(self) -> None:
        cites = self.cites() or ()
        self._loading = True
        try:
            picked = max(self.passages.currentRow(), 0)
            self.passages.clear()
            for source in cites:
                item = QListWidgetItem(passage_title(source))
                item.setData(DETAIL_ROLE, passage_detail(source))
                self.passages.addItem(item)
            if self.passages.count():
                self.passages.setCurrentRow(min(picked, self.passages.count() - 1))
            self._show_passage()
        finally:
            self._loading = False

    def _project_id(self) -> NodeId | None:
        if self._step_id is None or not self._library.has(self._step_id):
            return None
        return self._library.project_of(self._step_id).id

    def _picked(self) -> FeatureSource | None:
        cites = self.cites()
        row = self.passages.currentRow()
        if cites is None or not 0 <= row < len(cites):
            return None
        return cites[row]

    def _show_passage(self) -> None:
        """The three fields follow the picked row — or go blank and quiet without one."""
        was_loading = self._loading
        self._loading = True
        try:
            source = self._picked()
            project_id = self._project_id()
            names = [""]
            if self._documents_of is not None and project_id is not None:
                names += self._documents_of(project_id)
            if source is not None and source.document not in names:
                names.append(source.document)  # A document since removed: still shown.
            self.document.clear()
            self.document.addItems(names)
            self.document.setCurrentIndex(names.index(source.document) if source else 0)
            self.page.setValue(source.page if source is not None and source.page else 0)
            if not self.quote.hasFocus():
                self.quote.setPlainText(source.quote if source is not None else "")
            for field in (self.document, self.page, self.quote):
                field.setEnabled(source is not None)
            self.remove_passage.setEnabled(source is not None)
        finally:
            self._loading = was_loading

    def _editing(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is not None and self.isAncestorOf(focus)

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID:
            return
        if origin is self and self._editing():
            return
        self.setEnabled(self.cites() is not None)
        self._reload()

    def _commit_passage(self) -> None:
        cites = self.cites()
        row = self.passages.currentRow()
        if self._loading or cites is None or not 0 <= row < len(cites):
            return
        before = cites[row]
        document = self.document.currentText().strip()
        quote = self.quote.toPlainText().strip()
        source = FeatureSource(
            document=document,
            quote=quote,
            page=self.page.value() or None,
            digest=self._digest(document)
            if (document, quote) != (before.document, before.quote)
            else before.digest,
        )
        if source == before:
            return
        self._push((*cites[:row], source, *cites[row + 1 :]))
        self.passages.item(row).setText(passage_title(source))
        self.passages.item(row).setData(DETAIL_ROLE, passage_detail(source))

    def _digest(self, document: str) -> str:
        project_id = self._project_id()
        if self._digest_of is None or project_id is None or not document:
            return ""
        return self._digest_of(project_id, document)

    def _add_passage(self) -> None:
        cites = self.cites()
        project_id = self._project_id()
        if cites is None or project_id is None:
            return
        names = self._documents_of(project_id) if self._documents_of else []
        self._push((*cites, FeatureSource(document=names[0] if names else "")))
        self.passages.setCurrentRow(self.passages.count() - 1)
        self.quote.setFocus()

    def _remove_passage(self) -> None:
        cites = self.cites()
        row = self.passages.currentRow()
        if cites is None or not 0 <= row < len(cites):
            return
        self._push((*cites[:row], *cites[row + 1 :]))

    def _push(self, cites: tuple[FeatureSource, ...]) -> None:
        if self._step_id is None or cites == self.cites():
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, write(cites), view_origin=self, label="Edit Passages"
            )
        )
