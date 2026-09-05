"""Reading PDFs for the spec workflow: a text layer, and a page rendered to an image.

The text layer is what makes a PDF a first-class spec document — ``spec show`` prints it,
a feature's quote anchors in it, ``spec diff`` diffs it — and a rendered page is
how a figure reaches the agent working a step. Pages are joined with a marker line so the
layer stays greppable and splittable; a page number in this module is always 1-based, the
number a person sees in a PDF viewer.

``pypdfium2`` is imported inside the functions on purpose: this file is reached at CLI
registry-build time through ``cli.py``, and loading pdfium's native library would tax every
``dplanner`` invocation for the few that actually open a PDF.
"""

import re
from pathlib import PurePosixPath
from typing import Any

from dplanner.core.png import encode_rgb

TEXT_DIR = "text"

_MARKER = "--- page {number} ---"
_MARKER_LINE = re.compile(r"^--- page (\d+) ---$")


def text_blob_name(document_file: str) -> str:
    """Where a document's text layer lives: ``text/<same stem>.txt``.

    Derived from the blob's own content-addressed name, never stored — so the previous
    version's layer is just ``text_blob_name(document.previous)``, and the index carries
    no pointer that could dangle.
    """
    return f"{TEXT_DIR}/{PurePosixPath(document_file).stem}.txt"


def text_layer(data: bytes) -> str:
    """Every page's text, each under its ``--- page N ---`` marker line."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        pages = []
        for number, page in enumerate(document, start=1):
            text = page.get_textpage().get_text_range().strip()
            pages.append(_MARKER.format(number=number) + "\n" + text)
        return "\n\n".join(pages) + "\n"
    finally:
        document.close()


def split_pages(layer: str) -> list[str]:
    """The layer as one string per page, marker lines removed; index 0 is page 1."""
    pages: list[str] = []
    current: list[str] | None = None
    for line in layer.splitlines():
        if _MARKER_LINE.match(line):
            if current is not None:
                pages.append("\n".join(current).strip())
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        pages.append("\n".join(current).strip())
    return pages


def quote_boxes(page: Any, quote: str) -> list[tuple[float, float, float, float]]:
    """Where ``quote`` is printed on a pdfium page: ``(left, bottom, right, top)`` boxes in
    PDF points, origin at the page's bottom-left — the viewer flips them.

    pdfium's search is exact, so a quote that only anchors whitespace-normalised is
    retried on its first line, and a quote it cannot find at all gives no boxes — the
    viewer then shows the page and nothing more, which is honest.
    """
    textpage = page.get_textpage()
    for needle in (" ".join(quote.split()), quote.strip().splitlines()[0] if quote.strip() else ""):
        if not needle:
            continue
        searcher = textpage.search(needle, match_case=False)
        hit = searcher.get_next()
        if hit is None:
            continue
        index, count = hit
        rects = textpage.count_rects(index, count)
        return [textpage.get_rect(number) for number in range(rects)]
    return []


def render_page(data: bytes, page_number: int, scale: float) -> bytes:
    """One page as a PNG. ``scale`` multiplies PDF points; 2.0 reads like 144 DPI."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        if not 1 <= page_number <= len(document):
            raise ValueError(f"no page {page_number} — the document has {len(document)} pages")
        bitmap = document[page_number - 1].render(scale=scale, rev_byteorder=True)
        return encode_rgb(bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer))
    finally:
        document.close()
