"""A two-line row for a ``QListWidget``: the name, and a quieter line under it — and
:class:`RichList`, the list those rows live in.

The shape a list of named things in a side panel wants — a spec document and when it
came — written once so the padding, the secondary tone and the elision agree. The
delegate reads the display text for the first line and :data:`DETAIL_ROLE` for the
second; an item's icon, when it has one, is drawn by the style and the text starts past
it. :data:`EMPHASIS_ROLE` bolds the first line and :data:`RULE_ROLE` draws a hairline
under the row — together they make a pinned row read as a header rather than as one
more entry.

A :class:`RichList` is the roster that is one column of things (DESIGN.md's *Lists of rich
items*): the table's well and its picked row, so a list and a table read as one family. A
reader who compares across rows wants ``framework/table.py`` instead.
"""

from typing import Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from dplanner.theme.cards import detail_font
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import (
    EDGE_W,
    ROW_LINE_GAP,
    ROW_PADDING_H,
    ROW_PADDING_V,
    SECONDARY_ALPHA,
)

ICON_GAP = 8  # Between a row's icon and its text.
RULE_ALPHA = 60  # The hairline under an emphasised row: a whisper of the text tone.

DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2
# A row drawn entirely in the secondary tone — something already dealt with.
MUTED_ROLE = int(Qt.ItemDataRole.UserRole) + 3
# The first line in bold — a row that names a thing of another kind than its neighbours.
EMPHASIS_ROLE = int(Qt.ItemDataRole.UserRole) + 4
# A hairline along the row's bottom edge — the pinned row's border with the list below.
RULE_ROLE = int(Qt.ItemDataRole.UserRole) + 5
# A note at the right of the first line, in the secondary tone: a shortcut, a count, a
# date — a fact *about* the row that reads as a column rather than as part of the name.
TRAILING_ROLE = int(Qt.ItemDataRole.UserRole) + 6
# A ``QColor`` washed under every cell of the row (a milestone's, a failed test's) — read
# by ``framework/table.py``'s delegate, never asked of a callback.
TINT_ROLE = int(Qt.ItemDataRole.UserRole) + 7
# The row is a group heading spanning the table: bold secondary words, never selected.
HEADING_ROLE = int(Qt.ItemDataRole.UserRole) + 8
# A ``QColor`` a table cell's first line is inked in: a semantic tone (a failed result) or a
# milestone's shade — a constant or a stored hex, never a palette colour, which goes stale.
INK_ROLE = int(Qt.ItemDataRole.UserRole) + 9
# What an editable table cell holds beside the words it prints. ``QTableWidgetItem`` keeps
# ``EditRole`` and ``DisplayRole`` as one value, so the number behind "3 d" needs a role.
VALUE_ROLE = int(Qt.ItemDataRole.UserRole) + 10
# The key a *collapsible* group heading is known by, and whether it is folded shut right
# now. A heading with no key is the plain spanned rule it always was; one with a key wears
# a disclosure chevron and swallows a click. See ``framework/table.py``'s ``add_heading``.
GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 11
COLLAPSED_ROLE = int(Qt.ItemDataRole.UserRole) + 12
# Set on a row that landed under a group heading, whether or not that heading folds: its
# first column hangs under the heading's words, so a group reads as holding its rows.
GROUPED_ROLE = int(Qt.ItemDataRole.UserRole) + 13
# Where a *host's* own roles start — the step id on a row, which milestone it is. Everything
# below this belongs to the delegates here, and a view that numbered its own roles from
# ``UserRole + 1`` had the order table draw its milestone label as a second line and grey
# every cell that carried a colour (2026-09-13). Number yours from this and nothing can
# collide with a role the framework adds later either.
HOST_ROLE = int(Qt.ItemDataRole.UserRole) + 16

TRAILING_GAP = 12  # Between the name and the note at the right, so neither crowds the other.


def rich_row_height(font: QFont) -> int:
    """Two lines of two sizes with the gap between and the padding around: the one
    formula a list row and a two-line table cell both take their height from."""
    return (
        2 * ROW_PADDING_V
        + QFontMetrics(font).height()
        + QFontMetrics(detail_font(font)).height()
        + ROW_LINE_GAP
    )


def text_left(option: QStyleOptionViewItem) -> int:
    """Where a row's text starts: past the padding, and past the icon when there is one."""
    left = option.rect.left() + ROW_PADDING_H
    if not option.icon.isNull():
        left += option.decorationSize.width() + ICON_GAP
    return left


class TwoLineDelegate(QStyledItemDelegate):
    """Two lines per row: the name, then what kind of thing it is or how it stands."""

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        left = text_left(opt)  # Measured with the icon in place; the icon is ours to draw.
        icon = QIcon(opt.icon)
        opt.icon = QIcon()
        style = opt.widget.style() if opt.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        palette = opt.palette
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = palette.ColorRole.HighlightedText if selected else palette.ColorRole.Text
        primary = palette.color(role)
        secondary = palette.color(role)
        secondary.setAlpha(SECONDARY_ALPHA)
        if index.data(MUTED_ROLE):
            primary = secondary

        rect = opt.rect.adjusted(ROW_PADDING_H, ROW_PADDING_V, -ROW_PADDING_H, -ROW_PADDING_V)
        metrics = opt.fontMetrics
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        if not icon.isNull():
            # On the first line, not centred on the row: a glyph is the name's, not the pair's.
            size = opt.decorationSize
            icon.paint(
                painter,
                QRect(
                    rect.left(),
                    rect.top() + (metrics.height() - size.height()) // 2,
                    size.width(),
                    size.height(),
                ),
            )
        rect.setLeft(left)
        name_font = QFont(opt.font)
        if index.data(EMPHASIS_ROLE):
            name_font.setBold(True)
            metrics = QFontMetrics(name_font)

        # The note at the right is drawn and measured first, so the name elides against
        # what is left rather than over it.
        trailing = index.data(TRAILING_ROLE) or ""
        name_width = rect.width()
        if trailing:
            note = opt.fontMetrics.horizontalAdvance(trailing)
            painter.setFont(opt.font)
            painter.setPen(secondary)
            painter.drawText(
                QRect(rect.right() - note, rect.top(), note, opt.fontMetrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                trailing,
            )
            name_width = max(0, name_width - note - TRAILING_GAP)

        painter.setFont(name_font)
        painter.setPen(primary)
        painter.drawText(
            QRect(rect.left(), rect.top(), name_width, metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, name_width),
        )
        painter.setFont(detail_font(opt.font))
        detail = QFontMetrics(detail_font(opt.font))
        painter.setPen(secondary)
        painter.drawText(
            QRect(
                rect.left(),
                rect.top() + opt.fontMetrics.height() + ROW_LINE_GAP,
                rect.width(),
                detail.height(),
            ),
            align,
            detail.elidedText(index.data(DETAIL_ROLE) or "", elide, rect.width()),
        )
        if index.data(RULE_ROLE):
            rule = palette.color(palette.ColorRole.Text)
            rule.setAlpha(RULE_ALPHA)
            painter.setPen(rule)
            bottom = opt.rect.bottom()
            painter.drawLine(opt.rect.left(), bottom, opt.rect.right(), bottom)
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> QSize:
        return QSize(0, rich_row_height(option.font))


class _EdgedRowDelegate(TwoLineDelegate):
    """The two-line row, wearing the table's picked edge on its left.

    Painted, as the table paints it, rather than drawn as the item's border: a border on an
    item hands the selection back to the style, which lays its own gradient under the ground
    the stylesheet asked for.
    """

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        super().initStyleOption(option, index)
        # No focus frame, as on the table: the style draws one round the current item, and a
        # second mark on the picked row is a second vocabulary for what the edge says.
        option.state &= ~QStyle.StateFlag.State_HasFocus

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            rect = option.rect
            edge = QRect(rect.left(), rect.top(), EDGE_W, rect.height())
            painter.fillRect(edge, option.palette.color(QPalette.ColorRole.Accent))


class RichList(QListWidget):
    """A list of two-line rows in the table's well, picked with the table's edge.

    The rows are :class:`TwoLineDelegate`'s, with the accent edge on a picked one; the well,
    the hover and the quiet picked ground are ``#RichList``'s rules. A list when there is one
    column of things; a table when a reader compares across rows (DESIGN.md's *Lists of rich
    items*).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RichList")
        self.setItemDelegate(_EdgedRowDelegate(self))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
