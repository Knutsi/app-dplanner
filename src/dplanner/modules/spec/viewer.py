"""Viewers for spec documents: markdown and text in a browser, PDFs via pdfium.

Two widgets, one rule each:

**Text resolves its images through the file area.** ``SpecTextBrowser.loadResource`` asks
the module's :class:`~dplanner.domain.store.ModuleFileArea` for a relative name, so
``![](assets/<hash>.png)`` renders against a folder, a git checkout or any other provider —
a viewer resolving ``QUrl.fromLocalFile`` would only work against one of them. Colours come
from the palette alone, so a theme switch costs nothing.

**PDF pages render lazily, on the GUI thread, one page at a time.** pdfium rasterises a
page in milliseconds and a page only renders when it scrolls into view, so the worst stall
is one page — and :class:`~dplanner.framework.task_runner.TaskRunner` offers no result
seam that would make marshalling a pixmap back worth the machinery. If enormous documents
ever bite, off-thread rendering is the named follow-up. The page's white sheet is the
document's own colour and is honest on both themes.
"""

from typing import Any

import pypdfium2 as pdfium
from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QImage,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QScrollArea, QTextBrowser, QVBoxLayout, QWidget

from dplanner.domain.store import ModuleFileArea

DOCUMENT_MARGIN = 12  # DESIGN.md: text never touches the frame.
LINE_HEIGHT_PERCENT = 130
PAGE_GAP = 12


def area_image(area: ModuleFileArea | None, name: QUrl | str) -> QImage | None:
    """A relative resource resolved through the file area — the one rule both the viewer
    and the editor answer ``loadResource`` with. None means "not ours; ask Qt"."""
    url = QUrl(name) if isinstance(name, str) else name
    if area is not None and url.isRelative():
        data = area.read_bytes(url.toString())
        if data is not None:
            image = QImage.fromData(data)
            if not image.isNull():
                return image
    return None


def style_document(document: QTextDocument) -> None:
    """Margin and line height for a spec's text — re-applied after ``setMarkdown``,
    which resets the document. Shared by the viewer and the editor so a document
    reads the same whichever one is showing it."""
    document.setDocumentMargin(DOCUMENT_MARGIN)
    block = QTextBlockFormat()
    block.setLineHeight(
        LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(block)


class SpecTextBrowser(QTextBrowser):
    """A read-only markdown/text well whose images come from the module file area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area: ModuleFileArea | None = None
        self.setOpenExternalLinks(True)
        self.document().setDocumentMargin(DOCUMENT_MARGIN)

    def show_markdown(self, area: ModuleFileArea, body: str) -> None:
        self._area = area
        self.setMarkdown(body)
        style_document(self.document())

    def show_text(self, body: str) -> None:
        self._area = None
        self.setPlainText(body)
        style_document(self.document())

    def loadResource(self, type: int, name: QUrl | str) -> Any:  # noqa: N802, A002 - Qt override
        image = area_image(self._area, name)
        return image if image is not None else super().loadResource(type, name)


class _PdfPage(QWidget):
    """One page: a fixed-aspect sheet that rasterises itself the first time it is painted."""

    def __init__(self, page: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page = page
        self._points = page.get_size()  # (width, height) in PDF points.
        self._cache: QPixmap | None = None

    def set_render_width(self, width: int) -> None:
        width = max(width, 1)
        height = round(width * self._points[1] / self._points[0])
        if width != self.width() or height != self.height():
            self._cache = None
            self.setFixedSize(width, height)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if self._cache is None or self._cache.deviceIndependentSize().width() != self.width():
            self._cache = self._render()
        if self._cache is not None:
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._cache)
            painter.end()

    def _render(self) -> QPixmap | None:
        ratio = self.devicePixelRatioF()
        scale = self.width() * ratio / self._points[0]
        if scale <= 0:
            return None
        bitmap = self._page.render(scale=scale, rev_byteorder=True)
        image = QImage(
            bitmap.buffer, bitmap.width, bitmap.height, bitmap.stride, QImage.Format.Format_RGB888
        ).copy()  # Detach from pdfium's buffer before it is freed.
        image.setDevicePixelRatio(ratio)
        return QPixmap.fromImage(image)


class PdfPageView(QScrollArea):
    """A vertical column of pages, sized to the viewport's width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._column = QWidget()
        self._column_layout = QVBoxLayout(self._column)
        self._column_layout.setContentsMargins(
            DOCUMENT_MARGIN, DOCUMENT_MARGIN, DOCUMENT_MARGIN, DOCUMENT_MARGIN
        )
        self._column_layout.setSpacing(PAGE_GAP)
        self._column_layout.addStretch(1)
        self.setWidget(self._column)
        self._document: Any = None
        self._pages: list[_PdfPage] = []

    def show_pdf(self, data: bytes) -> None:
        self.clear()
        self._document = pdfium.PdfDocument(data)
        layout = self._column_layout
        for page in self._document:
            sheet = _PdfPage(page, self._column)
            layout.insertWidget(layout.count() - 1, sheet)  # Keep the stretch last.
            self._pages.append(sheet)
        self._size_pages()

    def clear(self) -> None:
        for sheet in self._pages:
            sheet.setParent(None)
            sheet.deleteLater()
        self._pages.clear()
        if self._document is not None:
            self._document.close()
            self._document = None

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._size_pages()

    def _size_pages(self) -> None:
        width = self.viewport().width() - 2 * DOCUMENT_MARGIN
        for sheet in self._pages:
            sheet.set_render_width(width)
