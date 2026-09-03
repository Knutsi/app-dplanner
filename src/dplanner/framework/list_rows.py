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
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

ROW_PADDING_V = 10
ROW_PADDING_H = 12
ROW_LINE_GAP = 4
SECONDARY_ALPHA = 160  # ~63 % — DESIGN.md's opacity-derived secondary text.

ICON_GAP = 8  # Between a row's icon and its text.
RULE_ALPHA = 60  # The hairline under an emphasised row: a whisper of the text tone.

DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2
# A row drawn entirely in the secondary tone — something already dealt with.
MUTED_ROLE = int(Qt.ItemDataRole.UserRole) + 3
# The first line in bold — a row that names a thing of another kind than its neighbours.
EMPHASIS_ROLE = int(Qt.ItemDataRole.UserRole) + 4
# A hairline along the row's bottom edge — the pinned row's border with the list below.
RULE_ROLE = int(Qt.ItemDataRole.UserRole) + 5


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
        rect.setLeft(text_left(opt))  # The style drew the icon; the text starts past it.
        metrics = opt.fontMetrics
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        if index.data(EMPHASIS_ROLE):
            font = QFont(opt.font)
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetrics(font)
        painter.setPen(primary)
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width(), metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, rect.width()),
        )
        painter.setFont(opt.font)
        metrics = opt.fontMetrics
        painter.setPen(secondary)
        painter.drawText(
            QRect(
                rect.left(),
                rect.top() + metrics.height() + ROW_LINE_GAP,
                rect.width(),
                metrics.height(),
            ),
            align,
            metrics.elidedText(index.data(DETAIL_ROLE) or "", elide, rect.width()),
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
        metrics = option.fontMetrics
        return QSize(0, 2 * ROW_PADDING_V + 2 * metrics.height() + ROW_LINE_GAP)
