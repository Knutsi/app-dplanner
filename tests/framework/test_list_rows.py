"""The two-line row delegate: where the text starts, with and without an icon."""

import pytest
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


# -- the list primitive --------------------------------------------------------------------


def test_a_rich_list_is_the_two_line_rows_in_a_well_of_its_own_name(app):
    from dplanner.framework.list_rows import RichList, TwoLineDelegate

    made = RichList()
    try:
        assert made.objectName() == "RichList"
        assert isinstance(made.itemDelegate(), TwoLineDelegate)
    finally:
        made.deleteLater()


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_a_picked_rich_row_wears_the_tables_edge_over_the_quiet_ground(themed, theme):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QListWidgetItem

    from dplanner.framework.list_rows import DETAIL_ROLE, RichList
    from dplanner.theme import apply_theme
    from dplanner.theme.themes import DARK, LIGHT

    palette = {"dark": DARK, "light": LIGHT}[theme]
    apply_theme(themed, palette)
    made = RichList()
    for name in ("N2 · handoff", "N1 · decision"):
        item = QListWidgetItem(name)
        item.setData(DETAIL_ROLE, "13 September, on S15")
        made.addItem(item)
    made.resize(320, 200)
    made.show()
    themed.processEvents()
    try:
        made.setCurrentRow(1)
        themed.processEvents()
        rect = made.visualItemRect(made.item(1))
        image = made.viewport().grab().toImage()
        assert image.pixelColor(QPoint(rect.left() + 1, rect.center().y())) == QColor(
            palette.accent
        )
        # Clear of the words, which start at the left, and of the style's shading at the
        # item's own edges.
        ground = QPoint(rect.right() - rect.width() // 4, rect.center().y())
        assert image.pixelColor(ground) == QColor(palette.bg_overlay)
    finally:
        made.deleteLater()
