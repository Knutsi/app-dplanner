"""The bell in the menu bar's corner: a glyph and a few words, hidden when nothing stands."""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton, QWidget

from dplanner.modules.notices.sources import bell_text


class NoticeBell(QToolButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NoticeBell")
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Notices — click to open")
        self.hide()

    def set_icon(self, icon: QIcon) -> None:
        self.setIcon(icon)

    def show_notices(self, titles: Sequence[str]) -> None:
        text = bell_text(titles)
        if not text:
            self.hide()
            return
        self.setText(text)
        self.show()
