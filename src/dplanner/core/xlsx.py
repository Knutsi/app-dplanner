"""Writing an ``.xlsx`` workbook, with nothing but the standard library.

A workbook is a zip of a few XML parts, and DPlanner writes small tables into one; an
office-file library — or Qt, which the CLI must never load — would be the heavier
dependency for that. Deterministic on purpose: fixed zip timestamps, a fixed compression
level and a fixed part order, so the same sheets give the same bytes on every platform.

Strings are inline (no shared-string table), dates are Excel serial numbers wearing a
``yyyy-mm-dd`` format, the header row is bold and frozen, and a column is as wide as its
longest text within bounds. Odd content never raises: a NaN is an empty cell, and a
character XML cannot carry is dropped.
"""

import math
import re
import stat
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape, quoteattr

type Cell = str | float | int | date | None


@dataclass(frozen=True)
class Sheet:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]


_MAIN_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELATIONSHIP: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CONTENT_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_XML_HEAD: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Cell styles, by their index in styles.xml's <cellXfs>.
_PLAIN: Final = 0
_BOLD: Final = 1
_DATE: Final = 2
_DATE_FORMAT: Final = "yyyy-mm-dd"
_DATE_FORMAT_ID: Final = 164  # The first id Excel leaves free for a custom number format.

# Excel counts days from a day that never was: serial 60 is 1900-02-29, a Lotus 1-2-3 leap
# year bug kept for compatibility, so every later date is one more than the count from
# 1899-12-31 — which is the same as counting from the 30th.
_EPOCH_ORDINAL: Final = date(1899, 12, 30).toordinal()

_MIN_WIDTH: Final = 8
_MAX_WIDTH: Final = 60
_WIDTH_AIR: Final = 2  # Beyond the longest text, as Excel's own autofit leaves.

_NAME_LIMIT: Final = 31
_FORBIDDEN_IN_NAME: Final = frozenset("[]:*?/\\")

# What XML 1.0 cannot carry: C0 controls other than tab and newline, lone surrogates and
# the two non-characters. Dropped rather than refused, so a stray byte in a title never
# stops an export.
_UNWRITABLE: Final = re.compile(r"[\x00-\x08\x0b-\x1f\ud800-\udfff\ufffe\uffff]")

_ZIP_DATE_TIME: Final = (1980, 1, 1, 0, 0, 0)  # The earliest a zip entry can carry.
_COMPRESSION_LEVEL: Final = 9  # Fixed: determinism is part of the contract, not just size.
_UNIX: Final = 3  # ZipInfo.create_system otherwise follows the writing platform.
_REGULAR_FILE: Final = (stat.S_IFREG | 0o644) << 16


def workbook_bytes(sheets: Sequence[Sheet]) -> bytes:
    """The workbook as the bytes of an ``.xlsx`` file: the same bytes for the same sheets."""
    if not sheets:
        raise ValueError("a workbook needs at least one sheet")
    parts = [
        ("[Content_Types].xml", _content_types(len(sheets))),
        ("_rels/.rels", _PACKAGE_RELS),
        ("xl/workbook.xml", _workbook(_sheet_names(sheet.name for sheet in sheets))),
        ("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets))),
        ("xl/styles.xml", _STYLES),
        *(
            (f"xl/worksheets/sheet{number}.xml", _worksheet(sheet))
            for number, sheet in enumerate(sheets, start=1)
        ),
    ]
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, xml in parts:
            entry = zipfile.ZipInfo(name, date_time=_ZIP_DATE_TIME)
            entry.create_system = _UNIX
            entry.external_attr = _REGULAR_FILE
            archive.writestr(entry, xml.encode("utf-8"), zipfile.ZIP_DEFLATED, _COMPRESSION_LEVEL)
    return buffer.getvalue()


def write_xlsx(path: Path, sheets: Sequence[Sheet]) -> None:
    """Write the workbook to ``path`` so a crash never leaves a truncated file.

    The same write-then-rename as ``fsio.write_atomic``, which only takes text. The bytes
    are built before anything touches the disk, so a refused workbook leaves no file.
    """
    data = workbook_bytes(sheets)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _sheet_names(names: Iterable[str]) -> list[str]:
    """Every name as Excel accepts it, and no two the same — Excel compares them without case."""
    taken: set[str] = set()
    result: list[str] = []
    for raw in names:
        base = _legal_name(raw)
        name, copy = base, 1
        while name.casefold() in taken:
            copy += 1
            suffix = f" ({copy})"
            name = base[: _NAME_LIMIT - len(suffix)] + suffix
        taken.add(name.casefold())
        result.append(name)
    return result


def _legal_name(name: str) -> str:
    cleaned = "".join("_" if c in _FORBIDDEN_IN_NAME else c for c in _clean(name)).strip()
    return (cleaned or "Sheet")[:_NAME_LIMIT]


def _clean(text: str) -> str:
    return _UNWRITABLE.sub("", text)


def _column(index: int) -> str:
    """The letters of the ``index``-th column, counting from 1: A, B, … Z, AA, AB, …"""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _cell(ref: str, value: Cell, style: int) -> tuple[str, str] | None:
    """The text the cell shows and its markup, or None for a value that writes no cell."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, str):
        text = _clean(value)
        inline = f'<is><t xml:space="preserve">{escape(text)}</t></is>'
        return text, f'<c r="{ref}" s="{style}" t="inlineStr">{inline}</c>'
    if isinstance(value, bool):  # A bool passes as an int; written as what it is.
        return str(value).upper(), f'<c r="{ref}" s="{style}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, date):
        serial = value.toordinal() - _EPOCH_ORDINAL
        return _DATE_FORMAT, f'<c r="{ref}" s="{_DATE}"><v>{serial}</v></c>'
    return repr(value), f'<c r="{ref}" s="{style}"><v>{value!r}</v></c>'


def _worksheet(sheet: Sheet) -> str:
    table = [(sheet.columns, _BOLD), *((row, _PLAIN) for row in sheet.rows)]
    count = max(len(values) for values, _ in table)
    longest = [0] * count
    rows: list[str] = []
    for number, (values, style) in enumerate(table, start=1):
        cells: list[str] = []
        for index, value in enumerate(values, start=1):
            rendered = _cell(f"{_column(index)}{number}", value, style)
            if rendered is None:
                continue
            shown, markup = rendered
            cells.append(markup)
            longest[index - 1] = max(longest[index - 1], len(shown))
        rows.append(f'<row r="{number}">{"".join(cells)}</row>')
    last = f"{_column(max(count, 1))}{len(table)}"
    ref = "A1" if last == "A1" else f"A1:{last}"
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{_width(length)}" customWidth="1"/>'
        for index, length in enumerate(longest, start=1)
    )
    return (
        f"{_XML_HEAD}"
        f'<worksheet xmlns="{_MAIN_NS}">'
        f'<dimension ref="{ref}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"{f'<cols>{cols}</cols>' if cols else ''}"
        f"<sheetData>{''.join(rows)}</sheetData>"
        "</worksheet>"
    )


def _width(longest: int) -> int:
    return min(_MAX_WIDTH, max(_MIN_WIDTH, longest + _WIDTH_AIR))


def _workbook(names: Sequence[str]) -> str:
    sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{number}" r:id="rId{number}"/>'
        for number, name in enumerate(names, start=1)
    )
    return (
        f"{_XML_HEAD}"
        f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_RELATIONSHIP}">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    sheets = "".join(
        f'<Relationship Id="rId{number}" Type="{_RELATIONSHIP}/worksheet" '
        f'Target="worksheets/sheet{number}.xml"/>'
        for number in range(1, sheet_count + 1)
    )
    return (
        f"{_XML_HEAD}"
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{sheets}"
        f'<Relationship Id="rId{sheet_count + 1}" Type="{_RELATIONSHIP}/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def _content_types(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{number}.xml" '
        f'ContentType="{_CONTENT_TYPE}.worksheet+xml"/>'
        for number in range(1, sheet_count + 1)
    )
    return (
        f"{_XML_HEAD}"
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{_CONTENT_TYPE}.sheet.main+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{_CONTENT_TYPE}.styles+xml"/>'
        f"{sheets}"
        "</Types>"
    )


_PACKAGE_RELS: Final = (
    f"{_XML_HEAD}"
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{_RELATIONSHIP}/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)

# The least Excel opens without repairing: the first two fills must be none and gray125,
# and a cellStyles entry must name the Normal style. Style indices are _PLAIN, _BOLD, _DATE.
_STYLES: Final = (
    f"{_XML_HEAD}"
    f'<styleSheet xmlns="{_MAIN_NS}">'
    '<numFmts count="1">'
    f'<numFmt numFmtId="{_DATE_FORMAT_ID}" formatCode="{_DATE_FORMAT}"/>'
    "</numFmts>"
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    "</fonts>"
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    "</fills>"
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    f'<xf numFmtId="{_DATE_FORMAT_ID}" fontId="0" fillId="0" borderId="0" xfId="0" '
    'applyNumberFormat="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)
