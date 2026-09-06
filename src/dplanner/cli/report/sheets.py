"""The report's tables as spreadsheets: one table as CSV, every table as an XLSX workbook.

A spreadsheet is opened to sort, sum and chart, so a cell that reads as a number or an
ISO date is written as one — the column's kind says which to try — and everything else
stays the text the page shows. The order table already writes raw values for exactly
this reason (``step_order/export.py``); the formatted columns of the steps table travel as
text, which is honest about what they are.
"""

from datetime import date
from pathlib import Path

from dplanner.cli.report.assemble import Report
from dplanner.cli.report.parts import Column, Table
from dplanner.core.fsio import write_csv
from dplanner.core.xlsx import Cell, Sheet, workbook_bytes, write_xlsx


def csv_rows(table: Table) -> list[list[str]]:
    """The header and every row, as the CSV writes them."""
    return [[column.label for column in table.columns]] + [list(row.cells) for row in table.rows]


def write_table_csv(path: Path, table: Table) -> None:
    write_csv(path, csv_rows(table))


def sheet(table: Table) -> Sheet:
    return Sheet(
        table.title,
        tuple(column.label for column in table.columns),
        tuple(
            tuple(
                _cell(column, text) for column, text in zip(table.columns, row.cells, strict=True)
            )
            for row in table.rows
        ),
    )


def workbook(report: Report) -> list[Sheet]:
    """One sheet per table on the page, in page order; the workbook is never empty —
    the steps table is always there."""
    return [sheet(table) for table in report.tables()]


def workbook_for(report: Report) -> bytes:
    return workbook_bytes(workbook(report))


def write_workbook(path: Path, report: Report) -> None:
    write_xlsx(path, workbook(report))


def _cell(column: Column, text: str) -> Cell:
    if text == "":
        return None
    if column.kind in ("number", "days"):
        try:
            return float(text)
        except ValueError:
            return text
    if column.kind == "date":
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    return text
