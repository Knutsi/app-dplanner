r"""A table on the design system: one configuration and one delegate, every rule at once.

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

A group heading may be **collapsible**: give :meth:`Table.add_heading` a ``key`` and the
rows after it fold under it, behind a disclosure chevron the whole heading row is the target
for. What is folded is remembered **by key**, across the wholesale rebuild a host does on
every refresh, because a roster that reopened every group whenever anything changed would be
unusable — and the key is the host's word (a category's name), never a row number.

**A row that lands under a heading hangs under it.** Its first column is inset by the
chevron's slot, so the rows begin past the disclosure triangle rather than under it — the
shape every tree has, and what says the rows are the group's rather than merely following
it. Nothing else moves: the picked row's accent edge and its hover wash still run the row's
full width, because what is indented is where a row's name begins and not what counts as
the row.

A cell may carry an ink of its own — a result's tone, a milestone's shade — and a column may
carry a :class:`CellEditor`: a double-click, F2 or a typed key opens it over the cell, and a
committed value lands in the cell and is announced once through ``edited``, which the host
turns into a command. The editor is the table's rather than a widget planted in each cell,
so the row stays the unit of hover and selection and keeps the height the font gives it.

A column may also offer its usual values as :class:`Chip`\ s — painted in the cell, one
accent-filled for the value the row holds, committed with a click through the same
``edited``. Down a column of rows the chips line up into a grid, so the values are read by
position before a word of them is: which steps are small, which are large, which are not
sized at all. With an editor beside them a last chip opens it, and wears the row's value
when that is none of the chips, so a value off the scale is never shown as no value.

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
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QHelpEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QDateEdit,
    QDoubleSpinBox,
    QHeaderView,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.framework.list_rows import (
    COLLAPSED_ROLE,
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    GROUP_ROLE,
    GROUPED_ROLE,
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
    DENSE_GAP,
    EDGE_W,
    FIELD_GAP,
    RADIUS_SM,
    ROW_LINE_GAP,
    ROW_PADDING_H,
    ROW_PADDING_V,
    SECONDARY_ALPHA,
)

GLYPH_SLOT = KEY_BADGE_W  # Wide enough for a key badge; a glyph sits at its left.
CHEVRON_W = 12  # The disclosure triangle's slot on a collapsible heading.
CHEVRON_SIDE = 7.0  # The triangle itself, drawn inside that slot.
# How far a grouped row's first column hangs under its heading: the chevron's slot, so the
# rows begin past the disclosure triangle rather than under it.
GROUP_INDENT = CHEVRON_W + ICON_GAP
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
MORE_TEXT = "…"  # The last chip of a column with an editor, while the value is on the scale.
MORE_TIP = "Another value: type it in"
# Round a chip's words: a cell's side padding, so a one-digit size is still a fair target, and
# a dense gap above and below, so the chip sits inside the row the font sized.
CHIP_PAD_H = CELL_PADDING_H
CHIP_PAD_V = DENSE_GAP


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
class TextEditor:
    """Words typed into the cell — the plainest editor there is, and the one a roster of
    *names* wants. ``blank_text`` is what an empty value prints as, so a row with nothing
    in it still says what the column is for rather than showing a hole."""

    blank_text: str = ""
    placeholder: str = ""

    def make(self, parent: QWidget) -> QWidget:
        field = QLineEdit(parent)
        field.setPlaceholderText(self.placeholder)
        return field

    def load(self, editor: QWidget, value: object) -> None:
        assert isinstance(editor, QLineEdit)
        editor.setText(str(value) if isinstance(value, str) else "")
        editor.selectAll()  # A typed letter replaces the name, as it would in a field.

    def read(self, editor: QWidget) -> object:
        assert isinstance(editor, QLineEdit)
        return editor.text().strip()

    def text(self, value: object) -> str:
        return str(value) if isinstance(value, str) and value else self.blank_text


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
class Chip:
    """A value a column offers as one click: its words, what it means, and whether a hairline
    parts it from the chips before it — a value that is a claim of its own, not one more
    step along the scale."""

    value: object
    text: str
    tip: str = ""
    apart: bool = False


class _More:
    """What the last chip carries instead of a value: *open the editor*."""


MORE = _More()


@dataclass(frozen=True)
class LaidChip:
    """A chip where one row paints it, and whether it is that row's value."""

    chip: Chip
    rect: QRect
    checked: bool


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
    # The usual values, painted in the cell as chips and picked with a click; with an editor
    # a last chip opens it.
    chips: tuple[Chip, ...] = ()


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
        self._chip: tuple[int, int, int] | None = None  # (row, column, position) under the pointer.
        # Collapsible groups: which keys are folded (kept across a rebuild — the host's
        # refresh must not reopen what the reader shut), which heading row each key is on,
        # and which group each content row belongs to.
        self._collapsed: set[str] = set()
        self._heading_rows: dict[int, str] = {}
        self._row_group: dict[int, str] = {}
        self._filling: str = ""  # The key rows are landing under while a table is filled.
        self._grouped = False  # Whether a heading has been added: rows after one are indented.
        self._edit_on_release: QPersistentModelIndex | None = None
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

    def hovered_chip(self) -> tuple[int, int, int] | None:
        """The chip under the pointer, as (row, column, position along the cell)."""
        return self._chip

    def chips_at(self, row: int, column: int) -> list[LaidChip]:
        """The chips one cell paints, where it paints them, in viewport coordinates."""
        index = self.model().index(row, column)
        return self.delegate.chip_layout(index, self.visualRect(index))

    def chip_under(self, point: QPoint) -> tuple[int, int, int] | None:
        index = self.indexAt(point)
        if not index.isValid() or not self._columns[index.column()].chips:
            return None
        for position, laid in enumerate(self.chips_at(index.row(), index.column())):
            if laid.rect.contains(point):
                return index.row(), index.column(), position
        return None

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
            # Only the first column hangs under the heading: indenting every column would
            # be a second set of column positions for half the rows in the table.
            if column == 0 and self._grouped:
                item.setData(GROUPED_ROLE, True)
            for role, value in (data or {}).items():
                item.setData(role, value)
        if self._filling:
            # A row belongs to the last collapsible heading added before it, so a host
            # fills a grouped table exactly as it fills a flat one.
            self._row_group[row] = self._filling
            self.setRowHidden(row, self._filling in self._collapsed)
        return row

    def add_heading(
        self,
        text: str,
        *,
        ink: QColor | None = None,
        glyph: QIcon | None = None,
        key: str = "",
    ) -> int:
        """A group heading: one spanned row of bold secondary words that nothing selects.

        ``ink`` colours the words — a milestone's shade at the secondary alpha, so the
        heading over a milestone's rows says which milestone wherever else it is seen.
        ``glyph`` puts a picture in front of them, for a group that has one of its own.

        ``key`` makes the group **collapsible**: the rows added after it fold under this
        one, the heading wears a disclosure chevron and the whole row is the target that
        toggles it. Folded is remembered by key across a rebuild — see the module docstring.
        """
        row = self.rowCount()
        self.insertRow(row)
        for column in range(self.columnCount()):
            item = QTableWidgetItem(text if column == 0 else "")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData(HEADING_ROLE, True)
            item.setData(INK_ROLE, ink)
            if column == 0:
                item.setIcon(glyph if glyph is not None else QIcon())
                item.setData(GROUP_ROLE, key)
                item.setData(COLLAPSED_ROLE, key in self._collapsed)
            self.setItem(row, column, item)
        self.setSpan(row, 0, 1, self.columnCount())
        self.setRowHeight(row, row_height(self.font(), rich=False))
        self._filling = key
        self._grouped = True
        if key:
            self._heading_rows[row] = key
        return row

    # -- collapsing --------------------------------------------------------------------

    def collapsed(self) -> set[str]:
        """The group keys folded shut — what a host stores if it wants to outlive the tab."""
        return set(self._collapsed)

    def set_collapsed(self, key: str, folded: bool) -> None:
        """Fold or open one group, now and on every rebuild until it is said otherwise."""
        if folded == (key in self._collapsed):
            return
        self._collapsed.symmetric_difference_update({key})
        for row, found in self._heading_rows.items():
            if found == key and (item := self.item(row, 0)) is not None:
                item.setData(COLLAPSED_ROLE, folded)
        for row, found in self._row_group.items():
            if found == key:
                self.setRowHidden(row, folded)
        self.viewport().update()

    def group_at(self, row: int) -> str:
        """The collapsible group ``row`` is a heading for, or "" — what a click asks."""
        return self._heading_rows.get(row, "")

    def group_of(self, row: int) -> str:
        """The collapsible group ``row`` is *in*, or "" — what a host asks to open it.

        The other half of ``group_at``: that one asks whether a row heads a group, this
        one asks which group a row is under, which is what a host bringing one row on
        screen has to know before it can unfold what is hiding it.
        """
        return self._row_group.get(row, "")

    def is_heading(self, row: int) -> bool:
        """Whether ``row`` is a group heading rather than one of the things being listed."""
        item = self.item(row, 0)
        return item is not None and bool(item.data(HEADING_ROLE))

    def toggle_group(self, key: str) -> None:
        self.set_collapsed(key, key not in self._collapsed)

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
        # Which row was which goes; *what is folded* stays, keyed by the host's own word,
        # so a refresh between two keystrokes does not spring every group open.
        self._heading_rows.clear()
        self._row_group.clear()
        self._filling = ""
        self._grouped = False
        self._hover(None)
        self._hover_chip(None)

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
        self._hover_chip(None)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        super().mouseMoveEvent(event)
        self._hover_chip(self.chip_under(event.position().toPoint()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """A press on a collapsible heading folds it, and goes no further.

        The whole row is the target rather than the chevron alone: a heading selects
        nothing and runs nothing else, so there is no second thing a click there could
        have meant, and a seven-pixel triangle is not a target.
        """
        key = self.group_at(self.rowAt(event.position().toPoint().y()))
        if key and event.button() == Qt.MouseButton.LeftButton:
            self.toggle_group(key)
            return
        super().mousePressEvent(event)

    def edit_after_release(self, index: QModelIndex | QPersistentModelIndex) -> None:
        """Open the editor once the click that asked for it is over: Qt ends a release by
        setting the view back to no state, which would strand an editor opened inside it."""
        self._edit_on_release = QPersistentModelIndex(index)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        super().mouseReleaseEvent(event)
        pending, self._edit_on_release = self._edit_on_release, None
        if pending is not None and pending.isValid():
            self.edit(self.model().index(pending.row(), pending.column()))

    def _hover_chip(self, chip: tuple[int, int, int] | None) -> None:
        """A chip is a target of its own inside the row: it brightens, and the pointer says so."""
        if chip == self._chip:
            return
        self._chip = chip
        if chip is None:
            self.viewport().unsetCursor()
        else:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.viewport().update()

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

    def indent(self, index: QModelIndex | QPersistentModelIndex) -> int:
        """How far this cell hangs in: a grouped row's first column, and nothing else.

        One answer for the paint and the size hint, so a column sized to its contents has
        room for the indent it will be drawn with.
        """
        grouped = index.column() == 0 and bool(index.data(GROUPED_ROLE))
        return GROUP_INDENT if grouped else 0

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

    def _paint_heading_marks(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        ink: QColor,
    ) -> int:
        """A heading's chevron and glyph; returns where its words start.

        The chevron is drawn rather than vendored: like the key badge and the filter
        funnel it is a picture of *state* — open or shut — and its two forms are one
        triangle turned, which no icon set spells the same way twice.
        """
        left = option.rect.left() + self._table.padding()
        if index.data(GROUP_ROLE):
            middle = option.rect.center().y() + 1
            shut = bool(index.data(COLLAPSED_ROLE))
            half = CHEVRON_SIDE / 2
            centre = QPointF(left + CHEVRON_W / 2, float(middle))
            if shut:
                points = [
                    QPointF(centre.x() - half + 1, centre.y() - CHEVRON_SIDE),
                    QPointF(centre.x() - half + 1, centre.y() + CHEVRON_SIDE),
                    QPointF(centre.x() + half + 1, centre.y()),
                ]
            else:
                points = [
                    QPointF(centre.x() - CHEVRON_SIDE, centre.y() - half),
                    QPointF(centre.x() + CHEVRON_SIDE, centre.y() - half),
                    QPointF(centre.x(), centre.y() + half),
                ]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawPolygon(points)
            painter.restore()
            left += CHEVRON_W + ICON_GAP
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            slot = QRect(left, option.rect.center().y() - ICON_SIZE // 2, ICON_SIZE, ICON_SIZE)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            icon.paint(painter, slot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            left += ICON_SIZE + ICON_GAP
        return left

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
        if self._table.columns()[index.column()].chips and not heading:
            self._paint_chips(painter, opt, index)
            return

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
        metrics = opt.fontMetrics
        painter.save()
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if heading:
            left = self._paint_heading_marks(painter, opt, index, secondary)
        else:
            indent = self.indent(index)
            left = self.text_left(column, opt.rect) + indent
            glyphed = self._table.columns()[column].glyph
            if glyphed and isinstance(icon, QIcon) and not icon.isNull():
                slot = self.glyph_rect(opt.rect, metrics).translated(indent, 0)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                icon.paint(
                    painter, slot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
        width = max(0, opt.rect.right() - pad - left + 1)

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
        laid = self.chip_layout(index, QRect(0, 0, 0, height)) if not heading else []
        if laid:
            return QSize(laid[-1].rect.right() + 1 + self._table.padding(), height)
        return QSize(widest + slot + self.indent(index) + 2 * self._table.padding(), height)

    # -- chips -------------------------------------------------------------------------
    # Painted and hit-tested from one layout, so what is clicked is what was drawn. The
    # colours are the palette's — a chip's quiet ground is the buttons', its border the
    # hairline, the picked one the accent with its own ink — so a theme change needs nothing.

    def chip_layout(
        self, index: QModelIndex | QPersistentModelIndex, rect: QRect
    ) -> list[LaidChip]:
        column = self._table.columns()[index.column()]
        if not column.chips:
            return []
        value = index.data(VALUE_ROLE)
        offered = list(column.chips)
        if column.editor is not None:
            off_scale = value is not None and all(chip.value != value for chip in offered)
            words = column.editor.text(value) if off_scale else MORE_TEXT
            offered.append(Chip(MORE, words, MORE_TIP))
        font = self._table.font()
        # One width for every chip on the scale, so the columns of chips are a grid; the last
        # grows to what it has to say.
        unit = max(text_width(font, chip.text) for chip in column.chips) + 2 * CHIP_PAD_H
        height = min(rect.height() - 2 * DENSE_GAP, QFontMetrics(font).height() + 2 * CHIP_PAD_V)
        top = rect.top() + (rect.height() - height) // 2
        left = rect.left() + self._table.padding()
        laid: list[LaidChip] = []
        for position, chip in enumerate(offered):
            if position:
                left += 2 * FIELD_GAP + 1 if chip.apart else DENSE_GAP
            more = chip.value is MORE
            width = max(unit, text_width(font, chip.text) + 2 * CHIP_PAD_H) if more else unit
            checked = (words != MORE_TEXT) if more else chip.value == value
            laid.append(LaidChip(chip, QRect(left, top, width, height), checked))
            left += width
        return laid

    def _paint_chips(
        self,
        painter: QPainter,
        opt: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        palette = opt.palette
        editable = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
        text = palette.color(QPalette.ColorRole.Text)
        quiet = QColor(text)
        quiet.setAlpha(SECONDARY_ALPHA)
        if not editable:
            text = quiet = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        hairline = palette.color(QPalette.ColorRole.Mid)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._table.font())
        for position, laid in enumerate(self.chip_layout(index, opt.rect)):
            box = laid.rect
            if position and laid.chip.apart:
                x = box.left() - FIELD_GAP - 1
                painter.fillRect(
                    QRect(x, box.top() + DENSE_GAP, 1, box.height() - 2 * DENSE_GAP), hairline
                )
            over = editable and self._table.hovered_chip() == (
                index.row(),
                index.column(),
                position,
            )
            if laid.checked:
                ground = border = palette.color(QPalette.ColorRole.Accent)
                ink = palette.color(QPalette.ColorRole.BrightText)
            else:
                ground = palette.color(QPalette.ColorRole.Button)
                border = palette.color(QPalette.ColorRole.Light if over else QPalette.ColorRole.Mid)
                ink = text if over else quiet
            painter.setPen(QPen(border, 1))
            painter.setBrush(ground)
            painter.drawRoundedRect(
                QRectF(box).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS_SM, RADIUS_SM
            )
            painter.setPen(ink)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, laid.chip.text)
        painter.restore()

    def _chip_hit(
        self, index: QModelIndex | QPersistentModelIndex, rect: QRect, point: QPoint
    ) -> LaidChip | None:
        return next(
            (laid for laid in self.chip_layout(index, rect) if laid.rect.contains(point)), None
        )

    def editorEvent(  # noqa: N802 - Qt override
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """A click on a chip commits its value, or opens the editor from the last one. The
        press has already picked the row by then, so the panel follows the step being set."""
        if (
            isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)
        ):
            hit = self._chip_hit(index, option.rect, event.position().toPoint())
            if hit is not None:
                editable = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
                if event.type() == QEvent.Type.MouseButtonRelease and editable:
                    if hit.chip.value is MORE:
                        self._table.edit_after_release(index)
                    else:
                        self._commit(model, index, hit.chip.value)
                return True  # A double-click on a chip is two clicks on it, never the editor.
        return super().editorEvent(event, model, option, index)

    def helpEvent(  # noqa: N802 - Qt override
        self,
        event: QHelpEvent,
        view: QAbstractItemView,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            hit = self._chip_hit(index, option.rect, event.pos())
            if hit is not None and hit.chip.tip:
                QToolTip.showText(event.globalPos(), hit.chip.tip, view)
                return True
        return super().helpEvent(event, view, option, index)

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
        self._commit(model, index, spec.read(editor))

    def _commit(
        self,
        model: QAbstractItemModel,
        index: QModelIndex | QPersistentModelIndex,
        value: object,
    ) -> None:
        """A value into the cell, and announced — once, and only when it changed."""
        if value == index.data(VALUE_ROLE):
            return
        column = self._table.columns()[index.column()]
        if column.editor is not None:
            words = column.editor.text(value)
        else:
            words = next((chip.text for chip in column.chips if chip.value == value), "")
        model.setData(index, value, VALUE_ROLE)
        model.setData(index, words, Qt.ItemDataRole.DisplayRole)
        self._table.edited.emit(index.row(), index.column(), value)

    def updateEditorGeometry(  # noqa: N802 - Qt override
        self,
        editor: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Over the cell, and never narrower than the editor needs: a column sized to "3 d"
        # is narrower than a spin box with its arrows. Beside the chips it opens over the
        # last one, the chip it was opened from, and leaves the scale in sight.
        rect = QRect(option.rect)
        laid = self.chip_layout(index, option.rect)
        if laid:
            rect.setLeft(laid[-1].rect.left())
            rect.setWidth(editor.sizeHint().width())
        rect.setWidth(max(rect.width(), editor.sizeHint().width()))
        editor.setGeometry(rect)
