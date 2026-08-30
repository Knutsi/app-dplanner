"""What a test result looks like on screen: its colour, its chip, and its two-line row.

Shared by the step panel's Tests tab and the Tests table, so a failed test reads the same
wherever it is shown. The colours are **constant** ``QColor``s rather than theme fields —
``DESIGN.md``'s second deliberate exception, the same stance the progression board takes:
a status means one thing, and it must mean it on all twenty-two themes.
"""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QLabel, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from dplanner.modules.testing.runs import Outcome

# Semantic result colours, constant across themes (DESIGN.md deliberate exception #2).
OK_TINT = QColor(46, 160, 67)
FAILED_TINT = QColor(219, 68, 55)
SKIPPED_TINT = QColor(210, 153, 34)

TINTS = {"ok": OK_TINT, "failed": FAILED_TINT, "skipped": SKIPPED_TINT}
WORDS = {"ok": "Ok", "failed": "Failed", "skipped": "Skipped", "pending": "Not run"}

# A failed row is the one you came for, so it is the only one tinted; a wall of green
# would shout at every reader who was not looking for it.
FAILED_ROW_TINT = QColor(219, 68, 55, 26)

SECONDARY_ALPHA = 160  # The palette's text at ~63 %, as everywhere a painter has only it.
ROW_HEIGHT = 44
ROW_PADDING_X = 8
ROW_PADDING_Y = 6
LINE_GAP = 4


def word(status: str) -> str:
    return WORDS.get(status, status)


def tint(status: str) -> QColor | None:
    """The colour for a status, or ``None`` for pending — which is an absence, not a state."""
    return TINTS.get(status)


def outcome_line(outcome: Outcome | None) -> str:
    """Where a result came from, in one secondary line: the run, and what was noted."""
    if outcome is None:
        return ""
    where = outcome.run.label or outcome.run.id
    note = f" — {outcome.result.note}" if outcome.result.note else ""
    return f"{where}{note}"


class StatusChip(QLabel):
    """A dot and a word. Not a filled pill: at card size a pill is louder than the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.show_status("pending")

    def show_status(self, status: str) -> None:
        colour = tint(status)
        if colour is None:
            self.setText(WORDS["pending"])
            # Pending has no colour of its own; it borrows the panel's secondary text.
            self.setObjectName("InspectorNote")
        else:
            self.setText(f"● {word(status)}")
            self.setObjectName("")
            self.setStyleSheet(f"color: {colour.name()};")
        self.style().unpolish(self)
        self.style().polish(self)


class TestRowDelegate(QStyledItemDelegate):
    """One delegate for the whole table: a tint on failed rows, two lines on the test cell.

    Two lines because ``DESIGN.md`` says a list of rich items uses a delegate rather than
    concatenated ``\n`` text — and because a column of bare titles says nothing about what
    is actually verified, which is the whole reason somebody opened the table. A cell with
    no secondary line falls straight through to the default painting, so the delegate can
    sit on every column and only the test cell pays for it.

    Both flags are read off the index, never asked of a callback, so painting stays a pure
    function of the model — the stance ``step_order``'s release delegate takes.
    """

    SECONDARY_ROLE = int(Qt.ItemDataRole.UserRole) + 90
    FAILED_ROLE = int(Qt.ItemDataRole.UserRole) + 91

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Measure the text this delegate actually draws, not the blanked option's.

        ``initStyleOption`` clears the text so the style will not print it under ours, and
        the default hint measures that same emptied option — which sizes a two-line column
        to nothing. Both lines are measured here instead.
        """
        hint = super().sizeHint(option, index)
        secondary = index.data(self.SECONDARY_ROLE)
        if not secondary:
            return hint
        metrics = option.fontMetrics
        primary = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        widest = max(metrics.horizontalAdvance(primary), metrics.horizontalAdvance(str(secondary)))
        return QSize(widest + ROW_PADDING_X * 2, max(hint.height(), ROW_HEIGHT))

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        if index.data(self.SECONDARY_ROLE):
            # Blanked here rather than in paint(): the style re-initialises the option for
            # itself, so text cleared there comes back and prints under our own.
            option.text = ""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if index.data(self.FAILED_ROLE):
            painter.fillRect(option.rect, FAILED_ROW_TINT)
        secondary = index.data(self.SECONDARY_ROLE)
        # The style still paints the background, the selection and the focus ring; only
        # the text is ours, and only where there are two lines of it.
        super().paint(painter, option, index)
        if not secondary:
            return
        primary = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        colour = option.palette.color(role)
        faded = QColor(colour)
        faded.setAlpha(SECONDARY_ALPHA)

        metrics = option.fontMetrics
        body = option.rect.adjusted(ROW_PADDING_X, ROW_PADDING_Y, -ROW_PADDING_X, -ROW_PADDING_Y)
        top = QRect(body.left(), body.top(), body.width(), metrics.height())
        below = QRect(body.left(), top.bottom() + LINE_GAP, body.width(), metrics.height())

        painter.save()
        for rect, text, pen in ((top, primary, colour), (below, str(secondary), faded)):
            painter.setPen(pen)
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft, elided)
        painter.restore()
