"""The table primitive: the rules applied once, a row as the unit of hover and selection, a
heading nobody can pick, heights from the font, and the accent edge rendered in both themes."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    HEADING_ROLE,
    ICON_GAP,
    MUTED_ROLE,
    TINT_ROLE,
)
from dplanner.framework.table import Cell, Column, Table
from dplanner.theme import apply_theme
from dplanner.theme.icons import ICON_SIZE, tag_icon
from dplanner.theme.themes import DARK, LIGHT

STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 40
COLUMNS = (
    Column("Step", glyph=True, detail=True, resize="interactive"),
    Column("Days", numeric=True),
    Column("Status"),
)


@pytest.fixture
def table(app):
    made = Table(COLUMNS)
    yield made
    made.deleteLater()


def test_columns_configure_the_header_and_the_view(table):
    header = table.horizontalHeader()
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    assert not header.highlightSections() and header.stretchLastSection()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents
    assert table.verticalHeader().isHidden() and not table.showGrid()
    assert not table.alternatingRowColors() and not table.wordWrap() and table.hasMouseTracking()
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.verticalHeader().defaultSectionSize() == table.row_height()
    assert table.objectName() == "Table"


def test_add_row_writes_text_roles_alignment_and_stamps_data(table):
    glyph = tag_icon("#ffffff")
    tint = QColor(150, 130, 220, 22)
    row = table.add_row(
        [Cell("Build the modal", detail="F7", glyph=glyph, emphasis=True), Cell("3 d")],
        tint=tint,
        data={STEP_ROLE: "abc"},
    )
    assert row == 0 and table.rowCount() == 1
    first, days, status = (table.item(0, column) for column in range(3))
    assert first.text() == "Build the modal" and first.data(DETAIL_ROLE) == "F7"
    assert first.data(EMPHASIS_ROLE) is True and not first.icon().isNull()
    assert days.text() == "3 d" and days.textAlignment() & Qt.AlignmentFlag.AlignRight
    assert first.textAlignment() & Qt.AlignmentFlag.AlignLeft
    assert status.text() == "" and status.data(STEP_ROLE) == "abc"
    assert all(table.item(0, column).data(TINT_ROLE) == tint for column in range(3))
    table.set_cell(0, 2, Cell("done", secondary=True))
    assert table.item(0, 2).data(MUTED_ROLE) is True


def test_a_heading_spans_the_table_and_is_never_selected(table):
    table.add_heading("Improvements #1")
    table.add_row(["Build the modal"])
    assert table.columnSpan(0, 0) == 3 and table.item(0, 0).data(HEADING_ROLE) is True
    table.selectRow(0)
    assert table.selectedItems() == []
    table.selectRow(1)
    assert {item.row() for item in table.selectedItems()} == {1}
    assert table.rowHeight(0) < table.rowHeight(1)  # One line, whatever the rows are.


def test_rich_tables_are_taller_than_plain_ones_and_follow_the_font(app):
    plain = Table((Column("A"),))
    rich = Table((Column("A", detail=True),))
    big_host = QWidget()
    font = big_host.font()
    font.setPointSizeF(font.pointSizeF() + 6)
    big_host.setFont(font)
    big = Table((Column("A"),), parent=big_host)
    try:
        assert rich.row_height() > plain.row_height()
        assert plain.row_height() % 4 == 0 and rich.row_height() % 4 == 0
        assert big.row_height() > plain.row_height()
        assert big.verticalHeader().defaultSectionSize() == big.row_height()
    finally:
        plain.deleteLater()
        rich.deleteLater()
        big_host.deleteLater()


def test_clear_rows_drops_spans_and_hover(table):
    table.add_heading("Milestone")
    table.add_row(["a"])
    table.clear_rows()
    assert table.rowCount() == 0 and table.hovered_row() is None
    table.add_row(["a"])
    assert table.columnSpan(0, 0) == 1


def test_hover_follows_the_row_not_the_cell(table, app):
    for name in ("a", "b", "c"):
        table.add_row([name, "1", ""])
    table.resize(400, 300)
    table.show()
    app.processEvents()
    viewport = table.viewport()
    QTest.mouseMove(viewport, table.visualRect(table.model().index(2, 1)).center())
    assert table.hovered_row() == 2
    QTest.mouseMove(viewport, table.visualRect(table.model().index(2, 2)).center())
    assert table.hovered_row() == 2
    QCoreApplication.sendEvent(table, QEvent(QEvent.Type.Leave))
    assert table.hovered_row() is None


def test_the_glyph_slot_is_reserved_on_every_row_of_a_glyph_column(table):
    delegate = table.itemDelegate()
    rect = table.visualRect(table.model().index(0, 0))
    from PySide6.QtCore import QRect

    box = QRect(10, 0, 200, 30)
    assert delegate.text_left(0, box) == 10 + table.padding() + ICON_SIZE + ICON_GAP
    assert delegate.text_left(2, box) == 10 + table.padding()
    assert rect is not None


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_a_picked_row_wears_the_accent_edge_and_keeps_its_tint(themed, theme):
    apply_theme(themed, theme)
    table = Table((Column("Step"), Column("Days", numeric=True), Column("Status")))
    tint = QColor(150, 130, 220, 60)
    table.add_row(["plain", "1", ""])
    table.add_row(["tinted", "2", ""], tint=tint)
    table.resize(400, 200)
    table.show()
    themed.processEvents()
    try:
        model = table.model()

        def ground(row: int) -> QColor:
            cell = table.visualRect(model.index(row, 2))
            image = table.viewport().grab().toImage()
            return image.pixelColor(cell.center())

        def edge(row: int) -> QColor:
            cell = table.visualRect(model.index(row, 0))
            image = table.viewport().grab().toImage()
            return image.pixelColor(QPoint(cell.left() + 1, cell.center().y()))

        table.selectRow(1)
        themed.processEvents()
        assert edge(1) == QColor(theme.accent)
        assert edge(0) != QColor(theme.accent)
        picked_tinted = ground(1)
        table.selectRow(0)
        themed.processEvents()
        assert edge(0) == QColor(theme.accent)
        assert ground(0) == QColor(theme.bg_overlay)  # The quiet ground, not the highlight.
        assert picked_tinted != ground(0)  # A picked row gains its ground; the tint stays.
    finally:
        table.deleteLater()
