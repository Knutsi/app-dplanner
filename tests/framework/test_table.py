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
from dplanner.theme.icons import tag_icon
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


def test_fit_columns_opens_an_interactive_column_at_its_content(table):
    table.add_row(["A step whose title runs on for quite a while before it ends", "1", ""])
    before = table.columnWidth(0)
    table.fit_columns()
    assert table.columnWidth(0) > before


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
    delegate = table.delegate
    rect = table.visualRect(table.model().index(0, 0))
    from PySide6.QtCore import QRect

    box = QRect(10, 0, 200, 30)
    from dplanner.framework.table import GLYPH_SLOT

    assert delegate.text_left(0, box) == 10 + table.padding() + GLYPH_SLOT + ICON_GAP
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


def test_a_glyph_sits_on_the_first_line_of_a_rich_row_and_mid_row_on_a_plain_one(app):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFontMetrics

    from dplanner.theme.icons import ICON_SIZE as SIZE
    from dplanner.theme.tokens import ROW_PADDING_V

    rich = Table((Column("A", glyph=True, detail=True),))
    plain = Table((Column("A", glyph=True),))
    try:
        box = QRect(0, 100, 300, rich.row_height())
        metrics = QFontMetrics(rich.font())
        top = rich.delegate.glyph_rect(box, metrics).top()
        assert top == 100 + ROW_PADDING_V + (metrics.height() - SIZE) // 2
        box = QRect(0, 100, 300, plain.row_height())
        assert plain.delegate.glyph_rect(box, metrics).top() == 100 + (box.height() - SIZE) // 2
    finally:
        rich.deleteLater()
        plain.deleteLater()


def test_a_rich_row_is_two_lines_of_two_sizes(app):
    from PySide6.QtGui import QFontMetrics

    from dplanner.framework.list_rows import rich_row_height
    from dplanner.framework.table import snap_up
    from dplanner.theme.cards import detail_font
    from dplanner.theme.tokens import ROW_LINE_GAP, ROW_PADDING_V

    table = Table((Column("A", detail=True),))
    try:
        font = table.font()
        small = detail_font(font)
        assert small.pointSizeF() == font.pointSizeF() - 1
        lines = QFontMetrics(font).height() + QFontMetrics(small).height()
        assert rich_row_height(font) == 2 * ROW_PADDING_V + lines + ROW_LINE_GAP
        assert table.row_height() == snap_up(rich_row_height(font))
    finally:
        table.deleteLater()


def test_a_column_sized_to_its_contents_shows_them_whole(app):
    """Two rules meet here, and each of them clipped a real table before it was written.

    A cell is *measured* in the weight it is painted in, so a bold milestone does not
    elide in a column its plain neighbours sized; and it is measured by the width the
    text lays out to rather than by its advance, which a glyph's right side bearing can
    exceed by a pixel — enough to render "10" as an ellipsis.
    """
    from PySide6.QtWidgets import QStyleOptionViewItem

    made = Table((Column("#", numeric=True), Column("Wave")))
    made.add_row(("10", "Wave 15"))
    made.add_row((Cell("15", emphasis=True), Cell("Wave 15", emphasis=True)))
    option = QStyleOptionViewItem()
    made.initViewItemOption(option)

    for column in (0, 1):
        plain = made.delegate.sizeHint(option, made.model().index(0, column))
        bold = made.delegate.sizeHint(option, made.model().index(1, column))
        assert bold.width() >= plain.width()
        for row in (0, 1):
            index = made.model().index(row, column)
            drawn = made.delegate.sizeHint(option, index).width() - 2 * made.padding()
            cell = made.item(row, column)
            assert cell is not None
            text = cell.text()
            font = made.delegate.font_for(option, index)
            assert made.delegate.elided(font, text, drawn) == text
    made.deleteLater()


def test_a_host_numbers_its_own_roles_from_one_the_delegate_never_reads(table):
    """``HOST_ROLE`` is the promise: what a view stamps on its rows is its own business.

    The order table numbered its roles from ``UserRole + 1`` and collided with
    ``DETAIL_ROLE``, so every milestone row printed its label as a second line and greyed
    itself through ``MUTED_ROLE``. A host that starts here cannot, and neither can it
    collide with a role the framework adds later.
    """
    from dplanner.framework.list_rows import HOST_ROLE

    framework_roles = {DETAIL_ROLE, MUTED_ROLE, EMPHASIS_ROLE, HEADING_ROLE, TINT_ROLE}
    assert all(role < HOST_ROLE for role in framework_roles)

    table.add_row(("A", "1", "ok"), data={HOST_ROLE: "step-7"})
    item = table.item(0, 0)
    assert item.data(HOST_ROLE) == "step-7"
    assert not item.data(DETAIL_ROLE) and not item.data(MUTED_ROLE)


def test_the_current_cell_wears_no_focus_frame(table):
    """Qt draws a focus rectangle round the current cell; the row's edge is the one mark."""
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    table.add_row(["a", "1", ""])
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_HasFocus
    table.delegate.initStyleOption(option, table.model().index(0, 0))
    assert not option.state & QStyle.StateFlag.State_HasFocus
    assert option.text == "" and option.icon.isNull()
