"""Widgets for the sync module's status-bar presence and its diff dialog."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import caption, make_text_well
from dplanner.theme.fonts import mono_font
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import CAPTION_GAP

DIFF_DIALOG_SIZE = (720, 560)


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


class DiffDialog(DialogFrame):
    """A compact, read-only view of what has changed since the last Save.

    A library spans repositories, so the dialog carries a picker; it stays hidden while
    there is only one repository with changes to show. *Save Now* is the primary — the
    flow's next step after reading what would be committed — and the dialog only asks
    for it (``save_requested``): the module runs the registered verb, so the button
    honours exactly the gate File ▸ Save does. Non-modal, built once and shown again.
    """

    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Changes Since Last Save", parent, size=DIFF_DIALOG_SIZE)
        self._sources: list[tuple[str, Callable[[], str]]] = []
        body, layout = self.body, self.body_layout

        # One block to show or hide: the caption goes with the picker it is over.
        self._picker_block = QWidget(body)
        block = QVBoxLayout(self._picker_block)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(CAPTION_GAP)
        block.addWidget(caption("Repository", self._picker_block))
        self._picker = QComboBox(self._picker_block)
        self._picker.currentIndexChanged.connect(self._show_current)
        block.addWidget(self._picker)
        self._picker_block.hide()
        layout.addWidget(self._picker_block)

        self._text = QPlainTextEdit(body)
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setFont(mono_font())
        make_text_well(self._text)
        self._text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Enter stays the primary's.
        self._highlighter = _DiffHighlighter(self._text.document())
        layout.addWidget(self._text, 1)

        self.add_dismiss("Close")
        self.save_button = self.set_primary("Save Now", self.save_requested.emit)

    def set_sources(self, sources: list[tuple[str, Callable[[], str]]]) -> None:
        """One (label, read-the-diff) pair per repository; the diff is read on demand."""
        self._sources = list(sources)
        self._picker.blockSignals(True)
        self._picker.clear()
        for label, _read in self._sources:
            self._picker.addItem(label)
        self._picker.blockSignals(False)
        self._picker_block.setVisible(len(self._sources) > 1)
        self._show_current()

    def _show_current(self) -> None:
        index = self._picker.currentIndex()
        if 0 <= index < len(self._sources):
            self.set_diff(self._sources[index][1]())
        else:
            self.set_diff("")

    def set_diff(self, text: str) -> None:
        self._text.setPlainText(text or "No changes since the last save.")
