"""The spec module's markdown editor: a rich-text well whose document *is* markdown.

``SpecMarkdownEditor`` edits a ``QTextDocument`` loaded with ``setMarkdown`` and read back
with ``toMarkdown`` — Qt's own round-trip, so the widget shows headings, lists and inline
images while the file on disk stays a markdown document any agent can read. The trade is
that Qt normalises the markdown it writes; the activity only saves a document the user
actually modified, so merely opening one never reformats it.

Images follow the viewer's rule: a relative ``![](assets/…)`` resolves through the module
file area, never the local filesystem. An image arriving by paste, drop or the Insert
Image… button is content-addressed into the same ``assets/`` directory the CLI's
``spec attach`` uses, then embedded at the cursor — so ``toMarkdown`` emits a plain
relative link and the document renders identically in the read-only viewer. What counts as
an arriving image is :mod:`dplanner.framework.mime_files`'s answer, shared with the prose
stack's editor so the two surfaces cannot disagree about a drop.

Typing is undone by the widget's own stack (Ctrl+Z inside the editor); the application
stack holds the session-level index replaces — see the activity.
"""

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import (
    QFont,
    QImage,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import QFileDialog, QTextEdit, QWidget

from dplanner.domain.store import ModuleFileArea
from dplanner.framework.markdown_view import area_image, style_document
from dplanner.framework.mime_files import IMAGE_FILTER, carries_files, payloads
from dplanner.modules.spec.documents import attach_asset

MARKDOWN_DIALECT = QTextDocument.MarkdownFeature.MarkdownDialectGitHub


class SpecMarkdownEditor(QTextEdit):
    """One markdown document, edited in place, images from the module file area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area: ModuleFileArea | None = None
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        for key, handler in (
            (QKeySequence.StandardKey.Bold, self.toggle_bold),
            (QKeySequence.StandardKey.Italic, self.toggle_italic),
        ):
            shortcut = QShortcut(key, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(handler)

    # -- the document ----------------------------------------------------------------------

    def open_markdown(self, area: ModuleFileArea, body: str) -> None:
        self._area = area
        # Qt's exporter silently drops an image whose alt text is empty, so a document
        # written as `![](assets/…)` would lose its images on the first save. Give every
        # bare image the same default alt Qt's own insertImage uses.
        self.document().setMarkdown(body.replace("![](", "![image]("), MARKDOWN_DIALECT)
        style_document(self.document())
        self.document().setModified(False)
        self.document().clearUndoRedoStacks()

    def body(self) -> str:
        return self.document().toMarkdown(MARKDOWN_DIALECT)

    def loadResource(self, type: int, name: QUrl | str) -> object:  # noqa: N802, A002 - Qt override
        image = area_image((self._area,) if self._area is not None else (), name)
        return image if image is not None else super().loadResource(type, name)

    # -- images in -------------------------------------------------------------------------

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802 - Qt override
        if carries_files(source, images_only=True):
            return True
        return bool(super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802 - Qt override
        if self._area is not None:
            items = payloads(source, images_only=True)
            if items:
                for item in items:
                    self._embed(item.data, item.filename)
                return
        super().insertFromMimeData(source)

    def insert_image_from_file(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(self, "Insert Image", "", IMAGE_FILTER)
        if filename and self._area is not None:
            path = Path(filename)
            self._embed(path.read_bytes(), path.name)

    def _embed(self, data: bytes, filename: str) -> None:
        assert self._area is not None
        name = attach_asset(self._area, data, filename)
        image = QImage.fromData(data)
        self.document().addResource(
            QTextDocument.ResourceType.ImageResource.value, QUrl(name), image
        )
        self.textCursor().insertImage(name)

    # -- formatting ------------------------------------------------------------------------
    # Widget-local verbs: they change the caret's formats, not the model, so they are
    # methods here rather than ActionSpecs — the session flush is where the model learns.

    def toggle_bold(self) -> None:
        bold = self.fontWeight() > QFont.Weight.Normal
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal if bold else QFont.Weight.Bold)
        self.mergeCurrentCharFormat(fmt)

    def toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.fontItalic())
        self.mergeCurrentCharFormat(fmt)

    def set_heading(self, level: int) -> None:
        """Make the current block a heading (1-6), or body text again (0).

        ``toMarkdown`` reads only ``headingLevel``, but the *look* comes from the char
        format — mirror what Qt's markdown importer writes (size adjustment ``4 - level``,
        bold) or the heading keeps body-text size until the document is reloaded.
        """
        cursor = self.textCursor()
        block = QTextBlockFormat()
        block.setHeadingLevel(level)
        cursor.mergeBlockFormat(block)
        fmt = QTextCharFormat()
        fmt.setProperty(QTextFormat.Property.FontSizeAdjustment, 4 - level if level else 0)
        fmt.setFontWeight(QFont.Weight.Bold if level else QFont.Weight.Normal)
        span = QTextCursor(cursor)
        span.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        span.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        span.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    def bullet_list(self) -> None:
        self.textCursor().createList(QTextListFormat.Style.ListDisc)

    def numbered_list(self) -> None:
        self.textCursor().createList(QTextListFormat.Style.ListDecimal)
