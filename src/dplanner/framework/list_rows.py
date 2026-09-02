"""A two-line row for a ``QListWidget``: the name, and a quieter line under it.

The shape every list of named things in a side panel wants — a spec document and when it
came, a feature and whether it is placed — written once so the padding, the secondary
tone and the elision agree across surfaces. The delegate reads the display text for the
first line and :data:`DETAIL_ROLE` for the second; a caller sets both on the item.
"""

from typing import Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

ROW_PADDING_V = 10
ROW_PADDING_H = 12
ROW_LINE_GAP = 4
SECONDARY_ALPHA = 160  # ~63 % — DESIGN.md's opacity-derived secondary text.

DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2
# A row drawn entirely in the secondary tone — something already dealt with.
MUTED_ROLE = int(Qt.ItemDataRole.UserRole) + 3


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
        metrics = opt.fontMetrics
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        painter.setPen(primary)
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width(), metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, rect.width()),
        )
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
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> QSize:
        metrics = option.fontMetrics
        return QSize(0, 2 * ROW_PADDING_V + 2 * metrics.height() + ROW_LINE_GAP)
