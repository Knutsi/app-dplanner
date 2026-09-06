"""The xlsx writer: a valid, deterministic workbook from plain tables, read back part by part."""

import io
import math
import xml.etree.ElementTree as ET
import zipfile
from datetime import date

import pytest

from dplanner.core.xlsx import Cell, Sheet, workbook_bytes, write_xlsx

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def sheet(
    *rows: tuple[Cell, ...], name: str = "Steps", columns: tuple[str, ...] = ("Key", "Title")
):
    return Sheet(name=name, columns=columns, rows=rows)


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def part(data: bytes, name: str) -> ET.Element:
    return ET.fromstring(parts(data)[name])


def first_sheet(*rows: tuple[Cell, ...], columns: tuple[str, ...] = ("Key", "Title")) -> ET.Element:
    return part(workbook_bytes([sheet(*rows, columns=columns)]), "xl/worksheets/sheet1.xml")


def dimension(root: ET.Element) -> str:
    return root.find(f"{MAIN}dimension").get("ref", "")  # type: ignore[union-attr]


def cells(root: ET.Element) -> dict[str, ET.Element]:
    return {c.get("r", ""): c for c in root.iter(f"{MAIN}c")}


def text_of(cell: ET.Element) -> str:
    return cell.findtext(f"{MAIN}is/{MAIN}t", default="")


def test_the_package_has_every_part_and_the_content_types_name_them():
    data = workbook_bytes([sheet(), sheet(name="Milestones")])
    names = list(parts(data))
    assert names == [
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        "xl/worksheets/sheet1.xml",
        "xl/worksheets/sheet2.xml",
    ]
    overrides = {
        o.get("PartName", ""): o.get("ContentType", "")
        for o in part(data, "[Content_Types].xml").iter(f"{CONTENT_TYPES}Override")
    }
    assert set(overrides) == {
        "/xl/workbook.xml",
        "/xl/styles.xml",
        "/xl/worksheets/sheet1.xml",
        "/xl/worksheets/sheet2.xml",
    }
    assert overrides["/xl/worksheets/sheet2.xml"].endswith("spreadsheetml.worksheet+xml")


def test_every_part_is_well_formed_xml():
    data = workbook_bytes(
        [sheet(("S1", "Build <the> modal & ship"), (None, 3.5), (date(2026, 9, 6),))]
    )
    for name, payload in parts(data).items():
        ET.fromstring(payload)  # raises ParseError if not
        assert payload.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'), name


def test_sheet_names_appear_in_the_workbook_in_order():
    data = workbook_bytes([sheet(name="Steps"), sheet(name="Milestones"), sheet(name="Time")])
    entries = list(part(data, "xl/workbook.xml").iter(f"{MAIN}sheet"))
    assert [e.get("name") for e in entries] == ["Steps", "Milestones", "Time"]
    assert [e.get("sheetId") for e in entries] == ["1", "2", "3"]
    rels = parts(data)["xl/_rels/workbook.xml.rels"].decode()
    for entry in entries:
        assert f'Id="{entry.get(RELATIONSHIP + "id")}" ' in rels


def workbook_names(*names: str) -> list[str]:
    data = workbook_bytes([sheet(name=n) for n in names])
    return [e.get("name", "") for e in part(data, "xl/workbook.xml").iter(f"{MAIN}sheet")]


def test_a_long_name_is_cut_to_thirty_one_characters():
    assert workbook_names("x" * 40) == ["x" * 31]


def test_forbidden_characters_leave_the_name():
    (name,) = workbook_names("a[b]c:d*e?f/g\\h")
    assert not set(name) & set("[]:*?/\\")
    assert name == "a_b_c_d_e_f_g_h"


def test_an_empty_name_still_names_a_sheet():
    assert workbook_names("", "   ", "???") == ["Sheet", "Sheet (2)", "___"]


def test_duplicate_names_get_suffixes_even_after_truncation_and_without_case():
    assert workbook_names("Steps", "steps", "Steps") == ["Steps", "steps (2)", "Steps (3)"]
    long_a, long_b = workbook_names("y" * 40, "y" * 35)
    assert long_a == "y" * 31
    assert long_b == "y" * 27 + " (2)"
    assert len(long_b) == 31


def test_header_cells_are_bold_inline_strings():
    root = first_sheet(columns=("Key", "Title"))
    header = cells(root)
    assert header["A1"].get("s") == "1"
    assert header["B1"].get("s") == "1"
    assert header["A1"].get("t") == "inlineStr"
    assert [text_of(header[ref]) for ref in ("A1", "B1")] == ["Key", "Title"]


def test_a_string_cell_round_trips_markup_and_leading_spaces():
    root = first_sheet(("  <a> & b",))
    cell = cells(root)["A2"]
    assert cell.get("t") == "inlineStr"
    assert cell.get("s") == "0"
    assert text_of(cell) == "  <a> & b"
    t = cell.find(f"{MAIN}is/{MAIN}t")
    assert t is not None
    assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"


def test_control_characters_are_dropped_but_tab_and_newline_stay():
    root = first_sheet(("a\x00b\x07c\td\ne\r",))
    assert text_of(cells(root)["A2"]) == "abc\td\ne"


def test_a_lone_surrogate_is_dropped_rather_than_refused():
    root = first_sheet(("ok\ud800",))
    assert text_of(cells(root)["A2"]) == "ok"


def test_a_number_cell_has_a_numeric_value():
    root = first_sheet((3, 2.5, -0.1))
    row = cells(root)
    assert row["A2"].get("t") is None
    assert [row[ref].findtext(f"{MAIN}v") for ref in ("A2", "B2", "C2")] == ["3", "2.5", "-0.1"]


def test_a_bool_is_a_boolean_cell_not_a_number():
    row = cells(first_sheet((True, False)))
    assert (row["A2"].get("t"), row["A2"].findtext(f"{MAIN}v")) == ("b", "1")
    assert (row["B2"].get("t"), row["B2"].findtext(f"{MAIN}v")) == ("b", "0")


def test_a_date_is_an_excel_serial_wearing_the_date_style():
    data = workbook_bytes([sheet((date(2026, 9, 6),), (date(1900, 3, 1),))])
    row = cells(part(data, "xl/worksheets/sheet1.xml"))
    assert (row["A2"].get("s"), row["A2"].findtext(f"{MAIN}v")) == ("2", "46271")
    assert row["A3"].findtext(f"{MAIN}v") == "61"  # The day after Excel's imaginary leap day.

    styles = part(data, "xl/styles.xml")
    xfs = styles.findall(f"{MAIN}cellXfs/{MAIN}xf")
    date_xf = xfs[2]
    formats = {f.get("numFmtId"): f.get("formatCode") for f in styles.iter(f"{MAIN}numFmt")}
    assert formats[date_xf.get("numFmtId")] == "yyyy-mm-dd"
    assert date_xf.get("applyNumberFormat") == "1"
    bold_font = list(styles.iter(f"{MAIN}font"))[int(xfs[1].get("fontId", ""))]
    assert bold_font.find(f"{MAIN}b") is not None


def test_none_and_non_finite_floats_write_no_cell():
    root = first_sheet((None, "kept", math.nan, math.inf, -math.inf))
    assert list(cells(root)) == ["A1", "B1", "B2"]
    assert dimension(root) == "A1:E2"


def test_the_header_row_is_frozen():
    pane = first_sheet().find(f"{MAIN}sheetViews/{MAIN}sheetView/{MAIN}pane")
    assert pane is not None
    assert pane.attrib == {
        "ySplit": "1",
        "topLeftCell": "A2",
        "activePane": "bottomLeft",
        "state": "frozen",
    }


def test_column_widths_follow_the_longest_text_and_are_clamped():
    root = first_sheet(
        ("x", "a much longer title in this cell", "z" * 200, date(2026, 9, 6)),
        columns=("K", "Title", "Description", "Due"),
    )
    widths = [float(c.get("width", "")) for c in root.iter(f"{MAIN}col")]
    assert widths[0] == 8  # The floor: one letter would be unreadably narrow.
    assert 32 < widths[1] < 40  # The 32-character title, with a little air.
    assert widths[2] == 60  # The ceiling.
    assert 10 <= widths[3] < 15  # A date shows as ten characters.
    assert all(c.get("customWidth") == "1" for c in root.iter(f"{MAIN}col"))


def test_the_dimension_covers_the_widest_row():
    root = first_sheet(("S1", "one", "extra", "wider than the header"))
    assert dimension(root) == "A1:D2"
    assert "D2" in cells(root)


def test_columns_past_z_are_lettered_aa_onwards():
    root = first_sheet(columns=tuple(f"c{i}" for i in range(28)))
    assert [ref for ref in cells(root) if not ref[0].isdigit()][25:] == ["Z1", "AA1", "AB1"]


def test_identical_sheets_give_identical_bytes():
    one = workbook_bytes([sheet(("S1", "Build"), (None, date(2026, 9, 6)), name="Steps")])
    two = workbook_bytes([sheet(("S1", "Build"), (None, date(2026, 9, 6)), name="Steps")])
    assert one == two == workbook_bytes([sheet(("S1", "Build"), (None, date(2026, 9, 6)))])


def test_zip_entries_carry_no_clock_and_no_platform():
    with zipfile.ZipFile(io.BytesIO(workbook_bytes([sheet()]))) as archive:
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.compress_type == zipfile.ZIP_DEFLATED


def test_an_empty_sheet_is_valid():
    root = first_sheet()
    assert dimension(root) == "A1:B1"
    assert list(cells(root)) == ["A1", "B1"]
    assert len(list(root.iter(f"{MAIN}row"))) == 1

    bare = part(workbook_bytes([Sheet("Bare", (), ())]), "xl/worksheets/sheet1.xml")
    assert dimension(bare) == "A1"
    assert bare.find(f"{MAIN}cols") is None  # An empty <cols> is one Excel repairs.
    assert bare.find(f"{MAIN}sheetData") is not None


def test_a_workbook_needs_a_sheet():
    with pytest.raises(ValueError, match="at least one sheet"):
        workbook_bytes([])


def test_write_xlsx_writes_the_same_bytes(tmp_path):
    sheets = [sheet(("S1", "Build"), name="Steps")]
    target = tmp_path / "plan.xlsx"
    write_xlsx(target, sheets)
    assert target.read_bytes() == workbook_bytes(sheets)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.xlsx"]  # No temp file left.


def test_a_refused_workbook_leaves_no_file(tmp_path):
    target = tmp_path / "plan.xlsx"
    with pytest.raises(ValueError):
        write_xlsx(target, [])
    assert list(tmp_path.iterdir()) == []
