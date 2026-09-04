"""Small shared widget helpers.

Nothing here is a framework concept — these are the three or four things every second
feature would otherwise reimplement slightly differently: a confirmation whose default is
"no", a centred column at a readable measure, and Ctrl+wheel zoom. Add to it sparingly;
a helper that only one feature uses belongs in that feature.
"""

from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

# DESIGN.md's text-well metrics: the text never touches the frame.
DOCUMENT_MARGIN = 12
LINE_HEIGHT_PERCENT = 130


def make_text_well(pane: QPlainTextEdit) -> None:
    """DESIGN.md's text well: the document keeps 12 px from the frame on every side."""
    pane.document().setDocumentMargin(DOCUMENT_MARGIN)


def space_lines(pane: QPlainTextEdit) -> None:
    """~130 % line height for anything longer than a label — reapplied per setPlainText."""
    block = QTextBlockFormat()
    block.setLineHeight(
        LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor = QTextCursor(pane.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(block)


def confirm(parent: QWidget | None, title: str, question: str) -> bool:
    """A Yes/No prompt for an action that throws work away; No is the default so Enter
    never discards anything."""
    buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    answer = QMessageBox.question(parent, title, question, buttons, QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def centered_column(content: QWidget, max_width: int) -> QWidget:
    """Wrap ``content`` so it sits centred at a readable measure.

    Stretch-column-stretch rather than an alignment flag: an aligned widget is given only
    its size hint, which would collapse an editor; this way the column takes all space up
    to its maximum width and the stretches absorb the rest, so the measure stays
    comfortable in a wide window and degrades gracefully in a narrow one.
    """
    content.setMaximumWidth(max_width)
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    layout.addWidget(content, stretch=100)
    layout.addStretch(1)
    return wrapper
