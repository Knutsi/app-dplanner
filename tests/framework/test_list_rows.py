"""The two-line row delegate: where the text starts, with and without an icon."""

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QStyleOptionViewItem

from dplanner.framework.list_rows import ICON_GAP, text_left
from dplanner.theme.tokens import ROW_PADDING_H


def _option(icon: QIcon | None) -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 0, 200, 40)
    option.decorationSize = QSize(16, 16)
    if icon is not None:
        option.icon = icon
    return option


def test_text_starts_past_the_padding(app):
    assert text_left(_option(None)) == 10 + ROW_PADDING_H


def test_text_starts_past_the_icon_when_there_is_one(app):
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("black"))
    assert text_left(_option(QIcon(pixmap))) == 10 + ROW_PADDING_H + 16 + ICON_GAP
