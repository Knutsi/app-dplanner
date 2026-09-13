"""A table on the design system: one configuration and one delegate, every rule at once.

DESIGN.md's *Tables* is the standard this implements. A :class:`Table` is a ``QTableWidget``
whose columns are declared (:class:`Column`: numeric, glyph, two-line, how it resizes) and
whose look is applied once: headers left-aligned over one hairline, no grid, rows selected
whole, no editing but in a column an editor is declared on, the row height set on the
vertical header from the font — the one mechanism that sizes a delegate-drawn row — and
never a pixel token. Its
:class:`TableDelegate` paints what the rules say a row wears: a hover wash on the row the
pointer is over (Qt's own hover is per cell), a 2 px accent edge on the left of a picked
row over a quiet ground (*lifted, not recoloured*: a tinted row keeps its tint), a glyph
slot reserved on every row of a glyph column so titles align, numbers right-aligned, a
secondary line under a cell's text where the column allows one, and a group heading as a
spanned row nobody can select.

A cell may carry an ink of its own — a result's tone, a milestone's shade — and a column may
carry a :class:`CellEditor`: a double-click, F2 or a typed key opens it over the cell, and a
committed value lands in the cell and is announced once through ``edited``, which the host
turns into a command. The editor is the table's rather than a widget planted in each cell,
so the row stays the unit of hover and selection and keeps the height the font gives it.

Three tables were written by hand before this one and disagreed on nine settings; the
``#OrderTable`` rules four widgets borrowed by name are what this replaces, one migration
at a time. ``modules/debug/design_example.py`` is the reference to copy from.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from PySide6.QtCore import (
    QAbstractItemModel,
    QDate,
    QEvent,
    QItemSelectionModel,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QFontMetricsF, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QDateEdit,
    QDoubleSpinBox,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    HEADING_ROLE,
    ICON_GAP,
    INK_ROLE,
    MUTED_ROLE,
    TINT_ROLE,
    VALUE_ROLE,
    rich_row_height,
)
from dplanner.framework.widgets import NumberBox
from dplanner.theme.cards import detail_font
from dplanner.theme.icons import ICON_SIZE, KEY_BADGE_W
from dplanner.theme.tokens import (
    CELL_PADDING_H,
    CELL_PADDING_V,
    EDGE_W,
    ROW_LINE_GAP,
    ROW_PADDING_H,
    ROW_PADDING_V,
    SECONDARY_ALPHA,
)

GLYPH_SLOT = KEY_BADGE_W  # Wide enough for a key badge; a glyph sits at its left.
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
DATE_FORMAT = "d MMM yyyy"  # A day as a date field prints one, in the application's English.


class CellEditor(Protocol):
    """How one column's cells are edited in place: the widget, a value into and out of it,
    and the words a value prints as — one answer, so a committed cell already reads the way
    the host's next refresh will print it."""

    def make(self, parent: QWidget) -> QWidget: ...

    def load(self, editor: QWidget, value: object) -> None: ...

    def read(self, editor: QWidget) -> object: ...

    def text(self, value: object) -> str: ...


@dataclass(frozen=True)
class NumberEditor:
    """A number typed into the cell. With ``blank_text`` the minimum means *no value*: it
    prints as the blank and reads back as None, so "nothing recorded" is sayable without
    taking zero, which is a claim of its own."""

    minimum: float
    maximum: float
    step: float = 1.0
    decimals: int = 0
    suffix: str = ""
    blank_text: str = ""

    def make(self, parent: QWidget) -> QWidget:
        box = NumberBox(parent)
        box.setRange(self.minimum, self.maximum)
        box.setDecimals(self.decimals)
        box.setSingleStep(self.step)
        box.setSuffix(self.suffix)
        box.setSpecialValueText(self.blank_text)
        return box

    def load(self, editor: QWidget, value: object) -> None:
        assert isinstance(editor, QDoubleSpinBox)
        editor.setValue(float(value) if isinstance(value, int | float) else self.minimum)
        editor.selectAll()  # A typed digit replaces the number, as it would in a field.

    def read(self, editor: QWidget) -> object:
        assert isinstance(editor, QDoubleSpinBox)
        editor.interpretText()
        value = editor.value()
        return None if self.blank_text and value <= self.minimum else value

    def text(self, value: object) -> str:
        if not isinstance(value, int | float):
            return self.blank_text
        return f"{value:g}{self.suffix}"


@dataclass(frozen=True)
class DateEditor:
    """A day, picked in the cell from a calendar. ``words`` prints a committed day the way
    the host prints one, so the cell does not change its mind when the host's refresh lands;
    a cell with no day prints ``blank_text`` and the calendar opens on today."""

    words: Callable[[date], str] | None = None
    blank_text: str = ""

    def make(self, parent: QWidget) -> QWidget:
        field = QDateEdit(parent)
        field.setCalendarPopup(True)
        field.setDisplayFormat(DATE_FORMAT)
        field.setLocale(QLocale(QLocale.Language.English))
        return field

    def load(self, editor: QWidget, value: object) -> None:
        assert isinstance(editor, QDateEdit)
        day = value if isinstance(value, date) else date.today()
        editor.setDate(QDate(day.year, day.month, day.day))

    def read(self, editor: QWidget) -> object:
        assert isinstance(editor, QDateEdit)
        picked = editor.date()
        return date(picked.year(), picked.month(), picked.day())

    def text(self, value: object) -> str:
        if not isinstance(value, date):
            return self.blank_text
        if self.words is not None:
            return self.words(value)
        day = QDate(value.year, value.month, value.day)
        return QLocale(QLocale.Language.English).toString(day, DATE_FORMAT)


@dataclass(frozen=True)
class Column:
    """What a column holds, so the table can apply the rule for it."""

    title: str
    numeric: bool = False  # Cells right-align so digits line up; the header stays left.
    glyph: bool = False  # Every row reserves the slot, so titles align with or without one.
    detail: bool = False  # Cells may carry a second line; the whole table takes rich-row metrics.
    resize: Resize = "contents"
    # Edited in place: a double-click, F2 or a typed key opens it over the cell, and a picked
    # row aims its keys at the first column that has one.
    editor: CellEditor | None = None


@dataclass(frozen=True)
class Cell:
    """One cell's content; a bare ``str`` is a ``Cell`` with only text."""

    text: str = ""  # In an editor's column, empty means the editor's words for ``value``.
    detail: str = ""
    glyph: QIcon | None = None
    secondary: bool = False  # The whole cell in the secondary tone (a finished step's row).
    emphasis: bool = False  # Bold: the one weight in a table, for a fixed point among its rows.
    ink: QColor | None = None  # The first line's colour: a result's tone, a milestone's shade.
    tooltip: str = ""
    value: object = None  # What an editor opens on, and what a commit replaces.
    editable: bool = True  # In an editor's column: off for a row with nothing to set there.


def snap_up(value: int) -> int:
    return -(-value // GRID) * GRID


def text_width(font: QFont, text: str) -> int:
    """The narrowest width ``text`` is drawn whole in, in ``font``.

    Two measures, and the wider wins, because each falls short on a real font. Qt elides
    against the *fractional* advance, so an integer advance rounded down (15 for 15.3)
    elides "10" in DejaVu Sans — the ceiling never does, on every font this was swept
    over. And ink can reach past the advance — a glyph's side bearing, Liberation Sans's
    "1" — which does not elide but is clipped when painted, so the bounding rect counts
    too. ``sizeHint`` measures with this so a column sized to its contents shows them.
    """
    laid_out = math.ceil(QFontMetricsF(font).horizontalAdvance(text))
    return max(laid_out, QFontMetrics(font).boundingRect(text).width())


def row_height(font: QFont, rich: bool) -> int:
    """From the font, never a pixel token: the UI font is the platform's and a fixed height
    clips two lines at twelve points. Rounded up onto the 4-point scale."""
    if rich:
        return snap_up(rich_row_height(font))
    return snap_up(2 * CELL_PADDING_V + QFontMetrics(font).height())


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
        # A committed edit, as (row, column, value): the host's cue to push its command.
        self.edited: Signal[int, int, object] = Signal("table.edited")
        self._editable = next(
            (position for position, column in enumerate(columns) if column.editor is not None),
            None,
        )
        self.setHorizontalHeaderLabels([column.title for column in columns])
        header = self.horizontalHeader()
        header.setDefaultAlignment(_LEFT)
        header.setHighlightSections(False)
        # The last column takes the slack unless a column asks for it: a short fact after a
        # stretching name would otherwise split that slack with it.
        header.setStretchLastSection(not any(column.resize == "stretch" for column in columns))
        for position, column in enumerate(columns):
            header.setSectionResizeMode(position, _RESIZE[column.resize])
        self.verticalHeader().setVisible(False)
        # A table takes its row height from the header, not from the delegate's hint;
        # without this a second line prints over the row below it.
        self.verticalHeader().setDefaultSectionSize(self.row_height())
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        if self._editable is None:
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        else:
            triggers = QAbstractItemView.EditTrigger
            self.setEditTriggers(
                triggers.DoubleClicked | triggers.EditKeyPressed | triggers.AnyKeyPressed
            )
            self.currentCellChanged.connect(self._aim)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(_SELECTION[selection])
        self.setMouseTracking(True)  # ``entered`` fires only with it.
        self.entered.connect(lambda index: self._hover(index.row()))
        self.viewportEntered.connect(lambda: self._hover(None))
        self.delegate = TableDelegate(self)
        self.setItemDelegate(self.delegate)

    # -- what it is --------------------------------------------------------------------

    def columns(self) -> tuple[Column, ...]:
        return self._columns

    def rich(self) -> bool:
        return self._rich

    def row_height(self) -> int:
        return row_height(self.font(), self._rich)

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

    def add_heading(self, text: str, *, ink: QColor | None = None) -> int:
        """A group heading: one spanned row of bold secondary words that nothing selects.

        ``ink`` colours the words — a milestone's shade at the secondary alpha, so the
        heading over a milestone's rows says which milestone wherever else it is seen.
        """
        row = self.rowCount()
        self.insertRow(row)
        for column in range(self.columnCount()):
            item = QTableWidgetItem(text if column == 0 else "")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData(HEADING_ROLE, True)
            item.setData(INK_ROLE, ink)
            self.setItem(row, column, item)
        self.setSpan(row, 0, 1, self.columnCount())
        self.setRowHeight(row, row_height(self.font(), rich=False))
        return row

    def set_cell(self, row: int, column: int, cell: Cell | str) -> None:
        if isinstance(cell, str):
            cell = Cell(cell)
        item = self.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.setItem(row, column, item)
        editor = self._columns[column].editor
        item.setText(cell.text if cell.text or editor is None else editor.text(cell.value))
        item.setData(DETAIL_ROLE, cell.detail)
        item.setData(MUTED_ROLE, cell.secondary)
        item.setData(EMPHASIS_ROLE, cell.emphasis)
        item.setData(INK_ROLE, cell.ink)
        item.setData(VALUE_ROLE, cell.value)
        item.setToolTip(cell.tooltip)
        item.setIcon(cell.glyph if cell.glyph is not None else QIcon())
        item.setTextAlignment(_RIGHT if self._columns[column].numeric else _LEFT)
        # A fresh item is editable; that never mattered while nothing could edit, and now
        # only a cell in an editor's column may be.
        if editor is not None and cell.editable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

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

    # -- editing -----------------------------------------------------------------------

    def _aim(self, row: int, column: int, _previous_row: int, _previous_column: int) -> None:
        """Keep the current cell in the editor's column: a row is picked whole and a typed
        key goes to the current cell, so this is what lets a picked row answer a digit."""
        if self._editable is not None and row >= 0 and column != self._editable:
            self.setCurrentCell(row, self._editable, QItemSelectionModel.SelectionFlag.NoUpdate)

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

    def glyph_rect(self, rect: QRect, metrics: QFontMetrics) -> QRect:
        """Where a row's glyph sits: on the first line of a rich row, never centred on the
        pair — the glyph is the name's — and on the one line of a plain one."""
        if self._table.rich():
            top = rect.top() + ROW_PADDING_V + (metrics.height() - ICON_SIZE) // 2
        else:
            top = rect.top() + (rect.height() - ICON_SIZE) // 2
        return QRect(rect.left() + self._table.padding(), top, GLYPH_SLOT, ICON_SIZE)

    def text_left(self, column: int, rect: QRect) -> int:
        """Where a cell's words start: past the padding, and past the glyph slot a glyph
        column reserves on every row, filled or not."""
        left = rect.left() + self._table.padding()
        if self._table.columns()[column].glyph:
            left += GLYPH_SLOT + ICON_GAP
        return left

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        # Blanked here rather than in paint(): the style re-initialises the option for
        # itself, so text cleared there comes back and prints under ours.
        option.text = ""
        option.icon = QIcon()
        # No focus frame: the style draws one round the *current cell*, and a dotted box
        # lingering on the last cell clicked is a second mark for what the row's edge says.
        option.state &= ~QStyle.StateFlag.State_HasFocus

    def font_for(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QFont:
        """A cell's weight: bold for a heading and for a fixed point among its rows.

        One answer, so what ``sizeHint`` measures is what ``paint`` draws.
        """
        font = QFont(option.font)
        if index.data(HEADING_ROLE) or index.data(EMPHASIS_ROLE):
            font.setBold(True)
        return font

    def elided(self, font: QFont, text: str, width: int) -> str:
        """``text`` as it will be drawn in ``font``, cut to ``width``."""
        return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width)

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
        ink = index.data(INK_ROLE)
        if isinstance(ink, QColor):
            primary = ink
        column = index.column()
        pad = self._table.padding()
        left = self.text_left(column, opt.rect)
        width = max(0, opt.rect.right() - pad - left + 1)
        metrics = opt.fontMetrics
        painter.save()
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if self._table.columns()[column].glyph and isinstance(icon, QIcon) and not icon.isNull():
            slot = self.glyph_rect(opt.rect, metrics)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            icon.paint(painter, slot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        font = self.font_for(opt, index)
        painter.setFont(font)
        painter.setPen(primary)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        detail = str(index.data(DETAIL_ROLE) or "")
        align = opt.displayAlignment
        if detail:
            line = QRect(left, opt.rect.top() + ROW_PADDING_V, width, metrics.height())
            painter.drawText(line, align, self.elided(font, text, width))
            small = QFontMetrics(detail_font(opt.font))
            painter.setFont(detail_font(opt.font))
            painter.setPen(secondary)
            line = QRect(left, line.top() + metrics.height() + ROW_LINE_GAP, width, small.height())
            painter.drawText(line, align, self.elided(detail_font(opt.font), detail, width))
        else:
            line = QRect(left, opt.rect.top(), width, opt.rect.height())
            painter.drawText(line, align, self.elided(font, text, width))
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """What the delegate draws, measured — the blanked option would size to nothing —
        at the row height the header was set to, so ``resizeColumnsToContents`` agrees."""
        heading = bool(index.data(HEADING_ROLE))
        # Measured in the weight it will be *painted* in — a bold milestone is wider than
        # the same words plain — and by ``text_width``, which is what keeps ``elided`` from
        # cutting a cell the column was supposed to fit: "10" became "…" twice, on two
        # fonts, for two different reasons.
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        detail = str(index.data(DETAIL_ROLE) or "")
        widest = max(
            text_width(self.font_for(option, index), text),
            text_width(detail_font(option.font), detail),
        )
        column = index.column()
        slot = GLYPH_SLOT + ICON_GAP if self._table.columns()[column].glyph else 0
        height = row_height(option.font, rich=self._table.rich() and not heading)
        return QSize(widest + slot + 2 * self._table.padding(), height)

    # -- editing -----------------------------------------------------------------------
    # The column's editor makes, loads and reads the widget; the table owns the rest. A
    # commit writes the value and the editor's words into the cell and is announced once, and
    # only when the value changed — a focus-out that changed nothing must push no command.
    # The announcement runs inside Qt's commitData: a host may write cells there, but a
    # ``clear_rows`` would take the index away from under the open editor.

    def _editor(self, index: QModelIndex | QPersistentModelIndex) -> CellEditor | None:
        return self._table.columns()[index.column()].editor

    def createEditor(  # noqa: N802 - Qt override
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = self._editor(index)
        if editor is None:
            return super().createEditor(parent, option, index)
        widget = editor.make(parent)
        if self._table.columns()[index.column()].numeric and isinstance(widget, QAbstractSpinBox):
            widget.setAlignment(_RIGHT)
        return widget

    def setEditorData(  # noqa: N802 - Qt override
        self, editor: QWidget, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        spec = self._editor(index)
        if spec is None:
            super().setEditorData(editor, index)
            return
        spec.load(editor, index.data(VALUE_ROLE))

    def setModelData(  # noqa: N802 - Qt override
        self,
        editor: QWidget,
        model: QAbstractItemModel,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        spec = self._editor(index)
        if spec is None:
            super().setModelData(editor, model, index)
            return
        value = spec.read(editor)
        if value == index.data(VALUE_ROLE):
            return
        model.setData(index, value, VALUE_ROLE)
        model.setData(index, spec.text(value), Qt.ItemDataRole.DisplayRole)
        self._table.edited.emit(index.row(), index.column(), value)

    def updateEditorGeometry(  # noqa: N802 - Qt override
        self,
        editor: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Over the cell, and never narrower than the editor needs: a column sized to "3 d"
        # is narrower than a spin box with its arrows.
        rect = QRect(option.rect)
        rect.setWidth(max(rect.width(), editor.sizeHint().width()))
        editor.setGeometry(rect)
