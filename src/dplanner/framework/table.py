"""A table on the design system: one configuration and one delegate, every rule at once.

DESIGN.md's *Tables* is the standard this implements. A :class:`Table` is a ``QTableWidget``
whose columns are declared (:class:`Column`: numeric, glyph, two-line, how it resizes) and
whose look is applied once: headers left-aligned over one hairline, no grid, rows selected
whole, no editing, the row height set on the vertical header from the font — the one
mechanism that sizes a delegate-drawn row — and never a pixel token. Its
:class:`TableDelegate` paints what the rules say a row wears: a hover wash on the row the
pointer is over (Qt's own hover is per cell), a 2 px accent edge on the left of a picked
row over a quiet ground (*lifted, not recoloured*: a tinted row keeps its tint), a glyph
slot reserved on every row of a glyph column so titles align, numbers right-aligned, a
secondary line under a cell's text where the column allows one, and a group heading as a
spanned row nobody can select.

Three tables were written by hand before this one and disagreed on nine settings; the
``#OrderTable`` rules four widgets borrowed by name are what this replaces, one migration
at a time. ``modules/debug/design_example.py`` is the reference to copy from.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    HEADING_ROLE,
    ICON_GAP,
    MUTED_ROLE,
    TINT_ROLE,
)
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import (
    CELL_PADDING_H,
    CELL_PADDING_V,
    ROW_LINE_GAP,
    ROW_PADDING_H,
    ROW_PADDING_V,
    SECONDARY_ALPHA,
)

EDGE_W = 2  # The picked row's accent edge — the width the active pane's top edge has.
HOVER_ALPHA = 12  # The text colour at ~5 %: a wash that says the row is a target.
GRID = 4  # Row heights land on the 4-point scale.

Resize = Literal["contents", "interactive", "stretch"]
Selection = Literal["single", "extended", "none"]
_RESIZE = {
    "contents": QHeaderView.ResizeMode.ResizeToContents,
    "interactive": QHeaderView.ResizeMode.Interactive,
    "stretch": QHeaderView.ResizeMode.Stretch,
}
_SELECTION = {
    "single": QAbstractItemView.SelectionMode.SingleSelection,
    "extended": QAbstractItemView.SelectionMode.ExtendedSelection,
    "none": QAbstractItemView.SelectionMode.NoSelection,
}
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


@dataclass(frozen=True)
class Column:
    """What a column holds, so the table can apply the rule for it."""

    title: str
    numeric: bool = False  # Cells right-align so digits line up; the header stays left.
    glyph: bool = False  # Every row reserves the slot, so titles align with or without one.
    detail: bool = False  # Cells may carry a second line; the whole table takes rich-row metrics.
    resize: Resize = "contents"


@dataclass(frozen=True)
class Cell:
    """One cell's content; a bare ``str`` is a ``Cell`` with only text."""

    text: str
    detail: str = ""
    glyph: QIcon | None = None
    secondary: bool = False  # The whole cell in the secondary tone (a finished step's row).
    emphasis: bool = False  # Bold: the one weight in a table, for a fixed point among its rows.


def snap_up(value: int) -> int:
    return -(-value // GRID) * GRID


def row_height(metrics: QFontMetrics, rich: bool) -> int:
    """From the font, never a pixel token: the UI font is the platform's and a fixed height
    clips two lines at twelve points. Rounded up onto the 4-point scale."""
    line = metrics.height()
    if rich:
        return snap_up(2 * ROW_PADDING_V + 2 * line + ROW_LINE_GAP)
    return snap_up(2 * CELL_PADDING_V + line)


class Table(QTableWidget):
    """The rules applied once; fill it with ``add_row`` and ``add_heading``."""

    def __init__(
        self,
        columns: Sequence[Column],
        *,
        selection: Selection = "single",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(0, len(columns), parent)
        self.setObjectName("Table")
        self._columns = tuple(columns)
        self._rich = any(column.detail for column in columns)
        self._hovered: int | None = None
        self.setHorizontalHeaderLabels([column.title for column in columns])
        header = self.horizontalHeader()
        header.setDefaultAlignment(_LEFT)
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        for position, column in enumerate(columns):
            header.setSectionResizeMode(position, _RESIZE[column.resize])
        self.verticalHeader().setVisible(False)
        # A table takes its row height from the header, not from the delegate's hint;
        # without this a second line prints over the row below it.
        self.verticalHeader().setDefaultSectionSize(self.row_height())
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(_SELECTION[selection])
        self.setMouseTracking(True)  # ``entered`` fires only with it.
        self.entered.connect(lambda index: self._hover(index.row()))
        self.viewportEntered.connect(lambda: self._hover(None))
        self.setItemDelegate(TableDelegate(self))

    # -- what it is --------------------------------------------------------------------

    def columns(self) -> tuple[Column, ...]:
        return self._columns

    def rich(self) -> bool:
        return self._rich

    def row_height(self) -> int:
        return row_height(self.fontMetrics(), self._rich)

    def padding(self) -> int:
        """The horizontal inset of a cell's content: a rich row's, or a plain cell's."""
        return ROW_PADDING_H if self._rich else CELL_PADDING_H

    def hovered_row(self) -> int | None:
        return self._hovered

    # -- filling it --------------------------------------------------------------------

    def add_row(
        self,
        cells: Sequence[Cell | str],
        *,
        tint: QColor | None = None,
        data: Mapping[int, object] | None = None,
    ) -> int:
        """Append a row. ``tint`` washes every cell; ``data`` is stamped on every cell under
        the host's own roles, so a click on any column answers the same question."""
        row = self.rowCount()
        self.insertRow(row)
        for column in range(self.columnCount()):
            self.set_cell(row, column, cells[column] if column < len(cells) else "")
            item = self.item(row, column)
            if item is None:
                continue
            if tint is not None:
                item.setData(TINT_ROLE, tint)
            for role, value in (data or {}).items():
                item.setData(role, value)
        return row

    def add_heading(self, text: str) -> int:
        """A group heading: one spanned row of bold secondary words that nothing selects."""
        row = self.rowCount()
        self.insertRow(row)
        for column in range(self.columnCount()):
            item = QTableWidgetItem(text if column == 0 else "")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData(HEADING_ROLE, True)
            self.setItem(row, column, item)
        self.setSpan(row, 0, 1, self.columnCount())
        self.setRowHeight(row, row_height(self.fontMetrics(), rich=False))
        return row

    def set_cell(self, row: int, column: int, cell: Cell | str) -> None:
        if isinstance(cell, str):
            cell = Cell(cell)
        item = self.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.setItem(row, column, item)
        item.setText(cell.text)
        item.setData(DETAIL_ROLE, cell.detail)
        item.setData(MUTED_ROLE, cell.secondary)
        item.setData(EMPHASIS_ROLE, cell.emphasis)
        item.setIcon(cell.glyph if cell.glyph is not None else QIcon())
        item.setTextAlignment(_RIGHT if self._columns[column].numeric else _LEFT)

    def clear_rows(self) -> None:
        self.clearSpans()
        self.setRowCount(0)
        self._hover(None)

    def fit_columns(self) -> None:
        """Open every ``interactive`` column at its content's width; call after filling.

        A ``contents`` column follows its cells on its own; an interactive one starts at
        Qt's default width, which is a riddle of ellipses until the person drags it.
        """
        for position, column in enumerate(self._columns):
            if column.resize == "interactive":
                self.resizeColumnToContents(position)

    # -- hover -------------------------------------------------------------------------

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self._hover(None)
        super().leaveEvent(event)

    def _hover(self, row: int | None) -> None:
        if row != self._hovered:
            self._hovered = row
            self.viewport().update()


class TableDelegate(QStyledItemDelegate):
    """Paints what a row wears; the style paints only its ground, selection and focus."""

    def __init__(self, table: Table) -> None:
        super().__init__(table)
        self._table = table

    def text_left(self, column: int, rect: QRect) -> int:
        """Where a cell's words start: past the padding, and past the glyph slot a glyph
        column reserves on every row, filled or not."""
        left = rect.left() + self._table.padding()
        if self._table.columns()[column].glyph:
            left += ICON_SIZE + ICON_GAP
        return left

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        # Blanked here rather than in paint(): the style re-initialises the option for
        # itself, so text cleared there comes back and prints under ours.
        option.text = ""
        option.icon = QIcon()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        palette = opt.palette
        heading = bool(index.data(HEADING_ROLE))
        tint = index.data(TINT_ROLE)
        if isinstance(tint, QColor):
            painter.fillRect(opt.rect, tint)  # Over the ground: a picked row keeps its tint.
        if not heading and self._table.hovered_row() == index.row():
            wash = palette.color(QPalette.ColorRole.Text)
            wash.setAlpha(HOVER_ALPHA)
            painter.fillRect(opt.rect, wash)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected and not heading and index.column() == 0:
            edge = QRect(opt.rect.left(), opt.rect.top(), EDGE_W, opt.rect.height())
            painter.fillRect(edge, palette.color(QPalette.ColorRole.Accent))

        # Ink from the palette's text, never HighlightedText: the picked ground is the quiet
        # overlay, and on some themes the highlighted text is that very colour.
        primary = palette.color(QPalette.ColorRole.Text)
        secondary = QColor(primary)
        secondary.setAlpha(SECONDARY_ALPHA)
        if heading or index.data(MUTED_ROLE):
            primary = secondary
        column = index.column()
        pad = self._table.padding()
        left = self.text_left(column, opt.rect)
        width = max(0, opt.rect.right() - pad - left + 1)
        metrics = opt.fontMetrics
        painter.save()
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if self._table.columns()[column].glyph and isinstance(icon, QIcon) and not icon.isNull():
            top = opt.rect.top() + (opt.rect.height() - ICON_SIZE) // 2
            icon.paint(painter, QRect(opt.rect.left() + pad, top, ICON_SIZE, ICON_SIZE))

        font = QFont(opt.font)
        if heading or index.data(EMPHASIS_ROLE):
            font.setBold(True)
        painter.setFont(font)
        painter.setPen(primary)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        detail = str(index.data(DETAIL_ROLE) or "")
        align = opt.displayAlignment
        elide = Qt.TextElideMode.ElideRight
        if detail:
            line = QRect(left, opt.rect.top() + ROW_PADDING_V, width, metrics.height())
            painter.drawText(line, align, QFontMetrics(font).elidedText(text, elide, width))
            painter.setFont(opt.font)
            painter.setPen(secondary)
            line.translate(0, metrics.height() + ROW_LINE_GAP)
            painter.drawText(line, align, metrics.elidedText(detail, elide, width))
        else:
            line = QRect(left, opt.rect.top(), width, opt.rect.height())
            painter.drawText(line, align, QFontMetrics(font).elidedText(text, elide, width))
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """What the delegate draws, measured — the blanked option would size to nothing —
        at the row height the header was set to, so ``resizeColumnsToContents`` agrees."""
        metrics = option.fontMetrics
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        detail = str(index.data(DETAIL_ROLE) or "")
        widest = max(metrics.horizontalAdvance(text), metrics.horizontalAdvance(detail))
        column = index.column()
        slot = ICON_SIZE + ICON_GAP if self._table.columns()[column].glyph else 0
        heading = bool(index.data(HEADING_ROLE))
        height = row_height(metrics, rich=self._table.rich() and not heading)
        return QSize(widest + slot + 2 * self._table.padding(), height)
