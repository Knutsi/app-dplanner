"""One feature record, edited in place: title, description, where it came from, images.

Hosted twice — by the Features panel's dialog and by a feature step's Feature tab — so
the same widget edits the same record whichever way a person reached it. Every change is
a ``SetModuleDataCommand`` over the project's catalogue, labelled per record so editing
two features never merges into one undo step, and the widget reloads on a foreign change
with the same echo rule ``ModuleDataSection`` uses: its own write is ignored while one
of its fields has the focus.

The description is prose in a record — a string, not a ``.md`` — so it goes through the
text stack the way a test's body does: :class:`FeatureDescriptionField` describes it to
``TextBinding``, which buys positional undo, coalesced typing and the expand-to-a-modal
editor without anybody copying text into a dialog and back.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.assets import attach
from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId
from dplanner.domain.store import FilesFor
from dplanner.framework.asset_gallery import AssetGallery
from dplanner.framework.mime_files import IMAGE_FILTER
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.undo import UndoService
from dplanner.modules.feature.aspect import MODULE_ID
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    FeatureSource,
    read_catalogue,
    with_record,
    write_catalogue,
)

# DESIGN.md: within a block.
FIELD_GAP = 6
QUOTE_LINES = 4
DESCRIPTION_PLACEHOLDER = (
    "What this feature is, in the words a person would demo it with — and what done means."
)


def _label(feature_id: str) -> str:
    # Per record, so editing two features never merges into one undo step.
    return f"Edit Feature {feature_id}"


def _record(library: Library, project_id: NodeId, feature_id: str) -> FeatureRecord | None:
    if not library.has(project_id):
        return None
    return next(
        (r for r in read_catalogue(library.project(project_id)) if r.id == feature_id), None
    )


def _write(library: Library, project_id: NodeId, updated: FeatureRecord, origin: object) -> Command:
    records = with_record(read_catalogue(library.project(project_id)), updated)
    return SetModuleDataCommand(
        project_id,
        MODULE_ID,
        write_catalogue(records),
        view_origin=origin,
        label=_label(updated.id),
    )


class FeatureDescriptionField:
    """A record's description, described to the framework's text binding.

    ``_last`` is the shadow copy a whole-entry write cannot carry: ``module_data_changed``
    says *that* the catalogue changed, never how, so the field reports a foreign edit as
    one replace of the whole body — cheap and exact, and its own typing never takes
    that path.
    """

    def __init__(self, library: Library, project_id: NodeId, feature_id: str) -> None:
        self._library = library
        self._project_id = project_id
        self._feature_id = feature_id
        self._last = self.read()

    def read(self) -> str:
        record = _record(self._library, self._project_id, self._feature_id)
        return record.description if record is not None else ""

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        record = _record(self._library, self._project_id, self._feature_id)
        if record is None:  # The record went while the editor was open; write nothing.
            records = read_catalogue(self._library.project(self._project_id))
            return SetModuleDataCommand(self._project_id, MODULE_ID, write_catalogue(records))
        body = record.description
        spliced = body[:pos] + added + body[pos + len(removed) :]
        return _write(self._library, self._project_id, replace(record, description=spliced), origin)

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_data(node_id: NodeId, module_id: str, origin: object) -> None:
            if node_id != self._project_id or module_id != MODULE_ID:
                return
            previous, current = self._last, self.read()
            self._last = current
            if previous != current:
                applied(0, previous, current, origin)

        return self._library.module_data_changed.connect(on_data)


class _QuoteEdit(QPlainTextEdit):
    """A few lines of quoted spec, committed when the focus leaves — a line edit's
    ``editingFinished`` for a field that may wrap."""

    editing_finished = Signal()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self.editing_finished.emit()


class FeatureEditor(QWidget):
    """One record's fields, each committed through the undo stack as it is left."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None = None,
        documents_of: Callable[[NodeId], list[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._files = files
        self._documents_of = documents_of
        self._project_id: NodeId | None = None
        self._feature_id: str | None = None
        self._loading = False

        self.title = QLineEdit(self)
        self.title.setPlaceholderText("What the feature is called")
        self.title.editingFinished.connect(self._commit_fields)

        self.document = QComboBox(self)
        self.document.currentIndexChanged.connect(lambda _index: self._commit_fields())
        self.page = QSpinBox(self)
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("—")
        self.page.valueChanged.connect(lambda _value: self._commit_fields())
        self.quote = _QuoteEdit(self)
        self.quote.setPlaceholderText("The passage it was read from")
        self.quote.setFixedHeight(self.quote.fontMetrics().height() * QUOTE_LINES + 12)
        self.quote.editing_finished.connect(self._commit_fields)
        source_row = QHBoxLayout()
        source_row.setSpacing(FIELD_GAP)
        source_row.addWidget(self.document, 1)
        source_row.addWidget(QLabel("page", self))
        source_row.addWidget(self.page)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FIELD_GAP)
        form.addRow("Title", self.title)
        form.addRow("From", source_row)
        form.addRow("Quote", self.quote)

        self.description = ProseSection(
            self._field_for,
            undo,
            placeholder=DESCRIPTION_PLACEHOLDER,
            margin=0,
            expand_title="Feature",
        )

        self.gallery = AssetGallery(self, editable=False)
        self.attach_button = QPushButton("Attach Image…", self)
        self.attach_button.clicked.connect(self._attach)
        images_row = QHBoxLayout()
        images_row.setSpacing(FIELD_GAP)
        images_row.addWidget(QLabel("Images", self))
        images_row.addWidget(self.attach_button)
        images_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        layout.addLayout(form)
        layout.addWidget(self.description, 1)
        layout.addLayout(images_row)
        layout.addWidget(self.gallery)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self.show_record(None, None)

    # -- what is shown ---------------------------------------------------------------------

    def show_record(self, project_id: NodeId | None, feature_id: str | None) -> None:
        if (project_id, feature_id) != (self._project_id, self._feature_id):
            # Re-bind the description only on a different record: rebinding under the
            # user's own keystroke would drop the cursor to the top on every character.
            self._project_id, self._feature_id = project_id, feature_id
            self.description.show_target(feature_id if project_id is not None else None)
        self.setEnabled(self.record() is not None)
        self._reload()

    def record(self) -> FeatureRecord | None:
        if self._project_id is None or self._feature_id is None:
            return None
        return _record(self._library, self._project_id, self._feature_id)

    def dispose(self) -> None:
        self._unsubscribe()
        self.description.dispose()

    # -- internals -------------------------------------------------------------------------

    def _field_for(self, feature_id: str) -> FeatureDescriptionField | None:
        if self._project_id is None:
            return None
        return FeatureDescriptionField(self._library, self._project_id, feature_id)

    def _reload(self) -> None:
        record = self.record()
        self._loading = True
        try:
            names = [""]
            if self._documents_of is not None and self._project_id is not None:
                names += self._documents_of(self._project_id)
            source = record.source if record is not None else None
            if source is not None and source.document not in names:
                names.append(source.document)  # A document since removed: still shown.
            self.document.clear()
            self.document.addItems(names)
            self.document.setCurrentIndex(names.index(source.document) if source else 0)
            self.page.setValue(source.page if source is not None and source.page else 0)
            if not self.quote.hasFocus():
                self.quote.setPlainText(source.quote if source is not None else "")
            if not self.title.hasFocus():
                self.title.setText(record.title if record is not None else "")
            self.gallery.set_files(
                list(record.images) if record is not None else [],
                self._read_image,
                self._remove_image if record is not None else None,
            )
        finally:
            self._loading = False

    def _editing(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is not None and self.isAncestorOf(focus)

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._project_id or module_id != MODULE_ID:
            return
        if origin is self and self._editing():
            return
        self.setEnabled(self.record() is not None)
        self._reload()

    def _commit_fields(self) -> None:
        if self._loading:
            return
        record = self.record()
        if record is None or self._project_id is None:
            return
        document = self.document.currentText().strip()
        source = (
            FeatureSource(
                document=document,
                quote=self.quote.toPlainText().strip(),
                page=self.page.value() or None,
            )
            if document
            else None
        )
        updated = replace(record, title=self.title.text().strip() or record.title, source=source)
        if updated == record:
            return
        self._undo.push(_write(self._library, self._project_id, updated, self))

    def _area_read(self, name: str) -> bytes | None:
        if self._files is None or self._project_id is None:
            return None
        try:
            return self._files(self._project_id, MODULE_ID).read_bytes(name)
        except KeyError:
            return None

    def _read_image(self, name: str) -> bytes | None:
        return self._area_read(name)

    def _attach(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self, "Attach Image", "", IMAGE_FILTER)
        if chosen:
            self.attach_bytes(Path(chosen).read_bytes(), Path(chosen).name)

    def attach_bytes(self, data: bytes, filename: str) -> str | None:
        """Copy an image beside the project and name it in the record — the panel's
        button and a test both come through here."""
        record = self.record()
        if record is None or self._files is None or self._project_id is None:
            return None
        try:
            area = self._files(self._project_id, MODULE_ID)
        except KeyError:
            return None  # A project the store has never flushed has no directory yet.
        name = attach(area, data, filename)
        if name not in record.images:
            updated = replace(record, images=(*record.images, name))
            self._undo.push(_write(self._library, self._project_id, updated, self))
        return name

    def _remove_image(self, name: str) -> None:
        """Drop the reference; the file stays for `asset prune` — an attach is not undoable,
        and a removed reference is."""
        record = self.record()
        if record is None or self._project_id is None or name not in record.images:
            return
        updated = replace(record, images=tuple(n for n in record.images if n != name))
        self._undo.push(_write(self._library, self._project_id, updated, self))
