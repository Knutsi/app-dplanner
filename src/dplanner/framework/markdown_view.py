"""A read-only markdown well whose images come from module file areas.

The rule it exists for: **a relative image reference is resolved through the store, never
through the filesystem.** ``![](assets/<hash>.png)`` has to render against a folder, a git
checkout or a GitHub clone alike, and a viewer answering ``loadResource`` with
``QUrl.fromLocalFile`` would only work against the first. So the well is handed
:class:`~dplanner.domain.store.ModuleFileArea`\\ s and asks them.

It takes a *sequence* of areas rather than one, because a document assembled from several
nodes carries images from each of their own file areas. Assets are content-addressed
(``domain/assets.py``), so a name identifies one blob wherever it lives and "ask each area,
first hit wins" is exact rather than a heuristic.

Colours come from the palette alone, so a theme switch costs this widget nothing.
"""

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QWidget

from dplanner.domain.store import ModuleFileArea
from dplanner.framework.widgets import DOCUMENT_MARGIN, LINE_HEIGHT_PERCENT


def area_image(areas: Sequence[ModuleFileArea], name: QUrl | str) -> QImage | None:
    """A relative resource resolved through the file areas, or None for "not ours; ask Qt"."""
    url = QUrl(name) if isinstance(name, str) else name
    if not url.isRelative():
        return None
    for area in areas:
        data = area.read_bytes(url.toString())
        if data is None:
            continue
        image = QImage.fromData(data)
        if not image.isNull():
            return image
    return None


def style_document(document: QTextDocument) -> None:
    """DESIGN.md's text-well metrics, re-applied after every ``setMarkdown``.

    ``setMarkdown`` and ``setPlainText`` both rebuild the document and drop its block
    formats, so this is a call after the content rather than a setting made once.
    """
    document.setDocumentMargin(DOCUMENT_MARGIN)
    block = QTextBlockFormat()
    block.setLineHeight(
        LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(block)


class MarkdownView(QTextBrowser):
    """A read-only markdown or plain-text well; images come from the areas it is given."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._areas: tuple[ModuleFileArea, ...] = ()
        self.setOpenExternalLinks(True)
        self.document().setDocumentMargin(DOCUMENT_MARGIN)

    def show_markdown(self, body: str, areas: Sequence[ModuleFileArea] = ()) -> None:
        self._areas = tuple(areas)
        self.setMarkdown(body)
        style_document(self.document())

    def show_text(self, body: str) -> None:
        """Plain text resolves nothing: whatever it says, it is not markdown."""
        self._areas = ()
        self.setPlainText(body)
        style_document(self.document())

    def loadResource(self, type: int, name: QUrl | str) -> Any:  # noqa: N802, A002 - Qt override
        image = area_image(self._areas, name)
        return image if image is not None else super().loadResource(type, name)
