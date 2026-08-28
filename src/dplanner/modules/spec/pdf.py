"""Reading PDFs for the spec workflow: a text layer, and a page rendered to an image.

The text layer is what makes a PDF a first-class spec document — ``spec show`` prints it,
``spec mark`` validates quotes against it, ``spec diff`` diffs it — and a rendered page is
how a figure reaches the agent working a step. Pages are joined with a marker line so the
layer stays greppable and splittable; a page number in this module is always 1-based, the
number a person sees in a PDF viewer.

``pypdfium2`` is imported inside the functions on purpose: this file is reached at CLI
registry-build time through ``cli.py``, and loading pdfium's native library would tax every
``dplanner`` invocation for the few that actually open a PDF.
"""

import re
from pathlib import PurePosixPath

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


def find_quote(layer: str, quote: str) -> int | None:
    """The 1-based page a quote appears on, or None.

    Whitespace- and case-normalized, because PDF text extraction rewraps lines and loses
    ligatures — an anchor that failed on a line break would make validation noise.
    """
    needle = _normalized(quote)
    if not needle:
        return None
    for number, page in enumerate(split_pages(layer), start=1):
        if needle in _normalized(page):
            return number
    return None


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        return len(document)
    finally:
        document.close()


def render_page(data: bytes, page_number: int, scale: float) -> bytes:
    """One page as a PNG. ``scale`` multiplies PDF points; 2.0 reads like 144 DPI."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        if not 1 <= page_number <= len(document):
            raise ValueError(
                f"no page {page_number} — the document has {len(document)} pages"
            )
        bitmap = document[page_number - 1].render(scale=scale, rev_byteorder=True)
        return encode_rgb(bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer))
    finally:
        document.close()
