"""The report on paper: A4 pages through ``QTextDocument`` and ``QPdfWriter``.

The same :class:`~dplanner.cli.report.assemble.Report` the page renders, laid out by Qt's
rich-text engine — which paginates for free — with the chart, the timeline and the graph
rendered from ``drawings.py``'s very SVG strings through ``QSvgRenderer`` at three times
the layout size, so one drawing code path serves screen and print. A wide graph is cut into
page-wide strips stacked down the page rather than shrunk to a ribbon.

Qt's engine lays a printed document out in screen pixels (about 96 dpi) and scales it to
the writer, so widths here are those pixels; an A4 page minus the margins is ~640 of them.
Window-only by decision: PySide6-Essentials has this and no Chromium, and the HTML page
carries print CSS for anyone at a terminal.
"""

from __future__ import annotations

from datetime import date
from html import escape
from math import ceil
from pathlib import Path

from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QUrl
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)
from PySide6.QtSvg import QSvgRenderer

from dplanner.cli.report.assemble import Report
from dplanner.cli.report.drawings import LIGHT, chart_svg, graph_bounds, graph_svg, timeline_svg
from dplanner.cli.report.parts import (
    SLOT_TITLES,
    SLOTS,
    Chart,
    Figure,
    Graph,
    Part,
    Prose,
    Table,
    Timeline,
)
from dplanner.core.markdown import render as markdown
from dplanner.domain.schedule import format_date
from dplanner.identity import APP_NAME, APP_VERSION

FALLBACK_DPI = 96.0  # Qt's layout dpi when no screen answers (a headless test).
QT_PRINT_MARGIN_CM = 2.0  # The root-frame margin QTextDocument.print_ adds on every side.
RASTER = 3  # Pixels per layout pixel for the pictures: crisp at print resolution.
GRAPH_STRIP = 1400.0  # A graph wider than this is cut into strips, one under another.

STYLE = """
body { font-family: sans-serif; font-size: 10pt; color: #23262b; }
h1 { font-size: 20pt; font-weight: 600; margin-bottom: 2px; }
h2 { font-size: 15pt; font-weight: 600; margin-top: 18px; }
h3 { font-size: 11pt; font-weight: 600; color: #5d6169; margin-top: 14px; margin-bottom: 4px; }
p { margin-top: 4px; margin-bottom: 4px; }
.meta, .note, .label { color: #5d6169; font-size: 9pt; }
.value { font-size: 16pt; font-weight: 600; }
th { font-size: 8.5pt; color: #5d6169; font-weight: 600; }
td { font-size: 9pt; }
code { font-family: monospace; font-size: 9pt; }
"""


def write(report: Report, path: Path) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    # No writer margins: print_ lays an unpaginated document out with a 2 cm root-frame
    # margin of its own, and the two would stack to a 3.6 cm gutter.
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setTitle(f"{report.title} — plan report")
    writer.setCreator(f"{APP_NAME} {APP_VERSION}")
    document = QTextDocument()
    document.setDefaultStyleSheet(STYLE)
    document.setHtml(_html(report, document, _layout_width(writer)))
    document.print_(writer)


def _layout_width(writer: QPdfWriter) -> int:
    """The layout pixels across the page inside the margins print_ will apply.

    ``QTextDocument.print_`` lays an unpaginated document out at the screen's logical dpi,
    inside a 2 cm root-frame margin it adds itself, and scales the result to the writer —
    so a picture sized in those pixels fills the page exactly, and one sized for a guessed
    width is clipped (measured: a 640 px chart lost its last week).
    """
    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInchX() if screen is not None else FALLBACK_DPI
    inches = writer.pageLayout().paintRect(QPageLayout.Unit.Inch).width()
    margin = int(QT_PRINT_MARGIN_CM / 2.54 * dpi)
    return max(200, int(inches * dpi) - 2 * margin)


def _html(report: Report, document: QTextDocument, width: int) -> str:
    pictures = _Pictures(document, width)
    day = format_date(report.day, today=report.day)
    out = [f"<h1>{_t(report.title)}</h1>"]
    meta = f"Plan as of {_t(day)} {report.day.year}"
    if report.summary:
        meta = f"{_t(report.summary)} · {meta}"
    out.append(f'<p class="meta">{meta}</p>')
    first = True
    for slot in SLOTS:
        parts = report.sections.get(slot, ())
        if not parts:
            continue
        style = "" if first else ' style="page-break-before: always"'
        first = False
        out.append(f"<h2{style}>{_t(SLOT_TITLES[slot])}</h2>")
        figures = [part for part in parts if isinstance(part, Figure)]
        if figures:
            out.append(_figures(figures))
        for part in parts:
            if not isinstance(part, Figure):
                out.append(_part(part, pictures, report))
    out.append(
        f'<p class="note">Generated by {_t(APP_NAME)} {_t(APP_VERSION)} from the plan as it '
        f"stood on {_t(day)} {report.day.year}.</p>"
    )
    return "".join(out)


def _figures(figures: list[Figure]) -> str:
    # Rows rather than tiles: a page has no room for five columns of 16-point dates.
    rows = "".join(
        f'<tr><td width="28%"><span class="label">{_t(f.label)}</span></td>'
        f'<td width="30%"><span class="value">{_t(f.value)}</span></td>'
        f'<td><span class="note">{_t(f.note)}</span></td></tr>'
        for f in figures
    )
    return f'<table width="100%" cellpadding="4" cellspacing="0">{rows}</table>'


def _part(part: Part, pictures: _Pictures, report: Report) -> str:
    if isinstance(part, Table):
        return _table(part, report)
    if isinstance(part, Chart):
        return (
            f"<h3>{_t(part.title)}</h3>"
            + pictures.picture(f"chart-{part.id}", chart_svg(part, LIGHT))
            + (f'<p class="note">{_t(part.note)}</p>' if part.note else "")
        )
    if isinstance(part, Timeline):
        return f"<h3>{_t(part.title)}</h3>" + pictures.picture(
            f"timeline-{part.id}", timeline_svg(part, LIGHT)
        )
    if isinstance(part, Graph):
        return _graph(part, pictures)
    if isinstance(part, Prose):
        meta = f'<p class="meta">{_t(part.meta)}</p>' if part.meta else ""
        return f"<h3>{_t(part.title)}</h3>{meta}{markdown(part.markdown)}"
    return ""


def _table(table: Table, report: Report) -> str:
    head = "".join(f'<th align="left">{_t(c.label)}</th>' for c in table.columns)
    rows = []
    for row in table.rows:
        cells = []
        for column, text in zip(table.columns, row.cells, strict=True):
            align = ' align="right"' if column.kind in ("number", "days") else ""
            shown = _t(_dated(column.kind, text, report))
            cells.append(f"<td{align}>{f'<b>{shown}</b>' if row.strong else shown}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    note = f'<p class="note">{_t(table.note)}</p>' if table.note else ""
    return (
        f"<h3>{_t(table.title)}</h3>"
        f'<table width="100%" cellpadding="4" cellspacing="0" border="0">'
        f"<tr>{head}</tr>{''.join(rows)}</table>{note}"
    )


def _dated(kind: str, text: str, report: Report) -> str:
    if kind != "date" or not text:
        return text
    try:
        return format_date(date.fromisoformat(text), today=report.day)
    except ValueError:
        return text


def _graph(graph: Graph, pictures: _Pictures) -> str:
    svg = graph_svg(graph, LIGHT)
    if not svg:
        return ""
    x0, y0, width, height = graph_bounds(graph)
    # Equal strips, so every one prints at the same scale; the last is never a sliver.
    strips = max(1, ceil(width / GRAPH_STRIP))
    strip = width / strips
    out = ["<h3>The plan</h3>"]
    for index in range(strips):
        view = QRectF(x0 + index * strip, y0, strip, height)
        out.append(pictures.picture(f"graph-{index}", svg, view))
    return "".join(out)


class _Pictures:
    """SVG strings rendered into the document's image resources, page-wide."""

    def __init__(self, document: QTextDocument, width: int) -> None:
        self._document = document
        self._width = width

    def picture(self, name: str, svg: str, view: QRectF | None = None) -> str:
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if view is not None:
            renderer.setViewBox(view)
        size = view.size() if view is not None else renderer.defaultSize().toSizeF()
        width, height = max(1.0, size.width()), max(1.0, size.height())
        shown = min(self._width, int(width))
        image = QImage(
            int(shown * RASTER),
            int(shown * RASTER * height / width),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(QColor(LIGHT.surface))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
        painter.end()
        url = QUrl(f"report:{name}.png")
        self._document.addResource(QTextDocument.ResourceType.ImageResource, url, image)
        return f'<p><img src="{url.toString()}" width="{shown}"></p>'


def _t(text: str) -> str:
    return escape(text, quote=True)
