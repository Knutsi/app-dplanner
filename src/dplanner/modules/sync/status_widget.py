"""The sync status-bar widgets: the remote's state as a glyph and words, and the unsaved-changes
button.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from dplanner.theme.icons import ICON_SIZE


class IconLabel(QWidget):
    """A status-bar label with a small leading glyph, repainted on theme change."""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = QLabel(self)
        self._text = QLabel(self)
        self._text.setObjectName(object_name)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._icon)
        layout.addWidget(self._text)

    def set_icon(self, icon: QIcon) -> None:
        self._icon.setPixmap(icon.pixmap(ICON_SIZE, ICON_SIZE))

    def set_text(self, text: str) -> None:
        self._text.setText(text)


class UnsavedChangesButton(QToolButton):
    """The headline flag: hidden while the working tree matches the last Save."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UnsavedChangesButton")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("You have unsaved changes — click to review")
        self.hide()

    def set_dirty(self, dirty: bool, file_count: int) -> None:
        if not dirty:
            self.hide()
            return
        noun = "change" if file_count == 1 else "changes"
        self.setText(f"● {file_count} unsaved {noun}")
        self.show()
