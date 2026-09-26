"""A panel a strip control drops, for what a menu cannot hold.

A ``QMenu`` is a list of verbs, and it owns the keyboard while it is open: a slider in one
never gets an arrow key, and a row of buttons that should stay pressed closes the menu at
the first click. A :class:`Popover` is a ``Qt.Popup`` frame instead — it closes on a click
outside it or on Escape, as a menu does, and in between the controls in it keep their keys
and their state. :class:`PopoverButton` is the strip control that drops one: its face says
what is set (a ``FilterButton``'s rule, DESIGN.md's *Toolbars*), its tooltip what it is, and
a click on it while its popover is open closes it rather than opening it again.
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QFrame, QToolButton, QVBoxLayout, QWidget

from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP


class Popover(QFrame):
    """The panel: fill :attr:`body`, then :meth:`open_below` a control."""

    closed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popover")
        # A click on the control that opened it closes it and stops there — replayed, the
        # same click would open it again at once.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(FIELD_GAP, FIELD_GAP, FIELD_GAP, FIELD_GAP)
        self.body.setSpacing(CAPTION_GAP)

    def open_below(self, anchor: QWidget) -> None:
        """Show under ``anchor``, its left edge on the anchor's, kept on the anchor's screen
        — above it where there is no room below."""
        self.adjustSize()
        size = self.sizeHint()
        below = anchor.mapToGlobal(QPoint(0, anchor.height()))
        screen = QGuiApplication.screenAt(below) or anchor.screen()
        room = screen.availableGeometry()
        x = max(room.left(), min(below.x(), room.right() - size.width()))
        y = below.y()
        if y + size.height() > room.bottom():
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - size.height()
        self.move(x, y)
        self.show()
        self.activateWindow()
        first = self.nextInFocusChain()
        if first is not None and first is not self and self.isAncestorOf(first):
            first.setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        super().closeEvent(event)
        self.closed.emit()


class PopoverButton(QToolButton):
    """The strip control that drops a :class:`Popover`: a quiet button whose face carries
    what is set — ``Budget · 1p/2a · 50%`` — and stays pressed while it is open."""

    def __init__(self, text: str, parent: QWidget | None = None, *, tip: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("ToolbarButton")
        self.setText(text)
        self.setToolTip(tip)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popover = Popover(self)
        self.popover.closed.connect(lambda: self.setChecked(False))
        self.clicked.connect(self._toggle)

    def _toggle(self, checked: bool) -> None:
        if checked:
            self.popover.open_below(self)
        else:
            self.popover.close()
