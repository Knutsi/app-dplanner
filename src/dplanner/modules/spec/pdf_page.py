"""The PDF viewer for spec documents: pages via pdfium, rasterised lazily.

**Pages render on the GUI thread, one page at a time.** pdfium rasterises a page in
milliseconds and a page only renders when it scrolls into view, so the worst stall is one
page — and :class:`~dplanner.framework.task_runner.TaskRunner` offers no result seam that
would make marshalling a pixmap back worth the machinery. If enormous documents ever bite,
off-thread rendering is the named follow-up. The page's white sheet is the document's own
colour and is honest on both themes.

A cited passage is drawn as a wash over the boxes pdfium's own search finds for it
(:func:`~dplanner.modules.spec.pdf.quote_boxes`), in the accent at low alpha — DESIGN.md's
exception #2, a semantic tint that reads on the page's white whatever the theme. A quote
the search cannot place gets the page and nothing more.

Markdown and plain text are :class:`~dplanner.framework.markdown_view.MarkdownView`, which
is the framework's — a well resolving its images through the store is not a spec idea.
"""

from collections.abc import Sequence
from typing import Any

import pypdfium2 as pdfium
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from dplanner.framework.widgets import DOCUMENT_MARGIN
from dplanner.modules.spec.pdf import quote_boxes

PAGE_GAP = 12
WASH_ALPHA = 60
FOCUS_ALPHA = 110


class _PdfPage(QWidget):
    """One page: a fixed-aspect sheet that rasterises itself the first time it is painted."""

    def __init__(self, page: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page = page
        self._points = page.get_size()  # (width, height) in PDF points.
        self._cache: QPixmap | None = None
        # (left, bottom, right, top) in PDF points, and whether each is the focused one.
        self._boxes: list[tuple[tuple[float, float, float, float], bool]] = []

    def set_render_width(self, width: int) -> None:
        width = max(width, 1)
        height = round(width * self._points[1] / self._points[0])
        if width != self.width() or height != self.height():
            self._cache = None
            self.setFixedSize(width, height)

    def mark(self, quotes: Sequence[str], focus: str) -> bool:
        """Wash every box a quote is printed in; whether the focused one is on this page."""
        self._boxes = []
        found_focus = False
        for quote in quotes:
            boxes = quote_boxes(self._page, quote)
            is_focus = bool(focus) and quote == focus
            found_focus |= is_focus and bool(boxes)
            self._boxes += [(box, is_focus) for box in boxes]
        self.update()
        return found_focus

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if self._cache is None or self._cache.deviceIndependentSize().width() != self.width():
            self._cache = self._render()
        if self._cache is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)
        if self._boxes:
            scale = self.width() / self._points[0]
            wash = QColor(self.palette().highlight().color())
            painter.setPen(Qt.PenStyle.NoPen)
            for (left, bottom, right, top), is_focus in self._boxes:
                wash.setAlpha(FOCUS_ALPHA if is_focus else WASH_ALPHA)
                painter.setBrush(wash)
                # PDF points run up from the bottom-left corner; the widget runs down.
                rect = QRectF(
                    left * scale,
                    (self._points[1] - top) * scale,
                    (right - left) * scale,
                    (top - bottom) * scale,
                )
                painter.drawRect(rect.adjusted(-1, -1, 1, 1))
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

    def page_count(self) -> int:
        return len(self._pages)

    def scroll_to_page(self, number: int) -> None:
        """Bring 1-based page ``number`` to the top of the viewport."""
        if not 1 <= number <= len(self._pages):
            return
        self._column_layout.activate()  # Positions come from the layout pass.
        self.verticalScrollBar().setValue(max(0, self._pages[number - 1].y() - DOCUMENT_MARGIN))

    def show_quotes(self, quotes: Sequence[str], focus: str = "", page: int | None = None) -> None:
        """Wash every printed occurrence of ``quotes``; scroll to ``focus`` — to the page
        it is found on, else to ``page`` when the caller knows it."""
        landing = page
        for number, sheet in enumerate(self._pages, start=1):
            if sheet.mark(quotes, focus) and landing is None:
                landing = number
        if landing is not None:
            self.scroll_to_page(landing)

    def clear_quotes(self) -> None:
        for sheet in self._pages:
            sheet.mark((), "")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._size_pages()

    def _size_pages(self) -> None:
        width = self.viewport().width() - 2 * DOCUMENT_MARGIN
        for sheet in self._pages:
            sheet.set_render_width(width)
