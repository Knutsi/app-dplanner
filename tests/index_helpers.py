"""Driving the index tree from a test: a plain click on a row, and a folder found by its id.

Shared because the index is the one surface every feature adds a folder to: a test that
reached for "the first folder" by position broke the day Home took the top of the tree, and
one that finds its folder by segment id does not.
"""

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from dplanner.framework.index_panel import SEGMENT_ROLE


def folder(panel, segment_id):
    """The folder row of the segment registered as ``segment_id``."""
    tree = panel.tree
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item is not None and item.data(0, SEGMENT_ROLE) == segment_id:
            return item
    raise LookupError(f"no {segment_id!r} folder in the index")


def click(panel, item, modifiers=None, button=None):
    """A plain click on a row, as press-then-release through the panel's event filter.

    Hand-built events rather than QTest.mouseClick: QTest drives the QPA layer, whose
    button bookkeeping leaks into ``QApplication.mouseButtons()`` for later tests.
    """
    modifiers = Qt.KeyboardModifier.NoModifier if modifiers is None else modifiers
    button = Qt.MouseButton.LeftButton if button is None else button
    viewport = panel.tree.viewport()
    pos = QPointF(panel.tree.visualItemRect(item).center())
    for kind, held in (
        (QEvent.Type.MouseButtonPress, button),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            viewport,
            QMouseEvent(
                kind, pos, QPointF(viewport.mapToGlobal(pos.toPoint())), button, held, modifiers
            ),
        )
