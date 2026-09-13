"""A two-line row for a ``QListWidget``: the name, and a quieter line under it.

The shape a list of named things in a side panel wants — a spec document and when it
came — written once so the padding, the secondary tone and the elision agree. The
delegate reads the display text for the first line and :data:`DETAIL_ROLE` for the
second; an item's icon, when it has one, is drawn by the style and the text starts past
it. :data:`EMPHASIS_ROLE` bolds the first line and :data:`RULE_ROLE` draws a hairline
under the row — together they make a pinned row read as a header rather than as one
more entry.
"""

from typing import Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from dplanner.theme.cards import detail_font
from dplanner.theme.tokens import ROW_LINE_GAP, ROW_PADDING_H, ROW_PADDING_V, SECONDARY_ALPHA

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
