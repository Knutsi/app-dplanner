"""Widgets for the sync module's status-bar presence and its diff dialog."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
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


class _DiffHighlighter(QSyntaxHighlighter):
    """Minimal unified-diff colouring: additions, deletions, hunk headers.

    Backgrounds carry low alpha so they read on every theme (dark, light, sepia) without
    reaching into the theme system for a diff-specific palette entry.
    """

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._added = self._format(QColor(46, 160, 67, 55))
        self._removed = self._format(QColor(248, 81, 73, 55))
        self._hunk = self._format(QColor(121, 162, 227, 55))

    @staticmethod
    def _format(color: QColor) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setBackground(color)
        return fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        if text.startswith("@@"):
            self.setFormat(0, len(text), self._hunk)
        elif text.startswith("+") and not text.startswith("+++"):
            self.setFormat(0, len(text), self._added)
        elif text.startswith("-") and not text.startswith("---"):
            self.setFormat(0, len(text), self._removed)


class DiffDialog(QDialog):
    """A compact, read-only view of what has changed since the last Save."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiffDialog")
        self.setWindowTitle("Changes Since Last Save")
        self.resize(720, 560)

        self._text = QPlainTextEdit(self)
        self._text.setObjectName("DiffText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFamily("monospace")
        self._text.setFont(font)
        self._highlighter = _DiffHighlighter(self._text.document())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.addButton("&Save Now", QDialogButtonBox.ButtonRole.ActionRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self._text)
        layout.addWidget(buttons)

    def set_diff(self, text: str) -> None:
        self._text.setPlainText(text or "No changes since the last save.")
