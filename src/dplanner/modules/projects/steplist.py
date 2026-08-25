"""The step list inside a project tab: two-line rows, drawn by a delegate.

DESIGN.md requires a :class:`QStyledItemDelegate` rather than concatenated ``\\n`` text for
a list of rich items, and the reasons are all visible here: each row gets real padding, a
primary/secondary hierarchy, text that re-wraps on resize, and a selection state that
recolours both lines legibly.

Line one is the step. Line two is what is true about it — what it waits on, and whatever the
aspect modules had to say. A step with nothing on line two says so rather than leaving a
ragged gap.
"""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

# DESIGN.md: rows in a list of rich items get 10 px vertical and 12 px horizontal padding,
# with the row's content lines 4 px apart.
ROW_PADDING_V = 10
ROW_PADDING_H = 12
LINE_GAP = 4

# Secondary text as opacity rather than a theme colour: a painter has only the palette, and
# an alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160

type Index = QModelIndex | QPersistentModelIndex

SECONDARY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class StepRowDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Index) -> None:
        self.initStyleOption(option, index)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())

        primary = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        secondary = str(index.data(SECONDARY_ROLE) or "")
        base = option.palette.highlightedText() if selected else option.palette.text()
        colour = QColor(base.color())

        body = option.rect.adjusted(ROW_PADDING_H, ROW_PADDING_V, -ROW_PADDING_H, -ROW_PADDING_V)
        metrics = option.fontMetrics
        painter.setPen(colour)
        painter.setFont(option.font)
        painter.drawText(
            QRect(body.left(), body.top(), body.width(), metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(primary, Qt.TextElideMode.ElideRight, body.width()),
        )
        if secondary:
            faded = QColor(colour)
            faded.setAlpha(SECONDARY_ALPHA)
            painter.setPen(faded)
            small = QFont(option.font)
            small.setPointSizeF(max(option.font.pointSizeF() - 1.0, 1.0))
            painter.setFont(small)
            top = body.top() + metrics.height() + LINE_GAP
            painter.drawText(
                QRect(body.left(), top, body.width(), body.bottom() - top),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                option.fontMetrics.elidedText(secondary, Qt.TextElideMode.ElideRight, body.width()),
            )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: Index) -> QSize:  # noqa: N802
        self.initStyleOption(option, index)
        lines = 2 if index.data(SECONDARY_ROLE) else 1
        height = option.fontMetrics.height() * lines + ROW_PADDING_V * 2
        if lines == 2:
            height += LINE_GAP
        return QSize(option.rect.width(), height)


class StepList(QListWidget):
    """The steps of one project, newest state redrawn wholesale — the list is short."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StepList")
        # Ids beside the rows rather than in an item role: one list, one index, and no
        # round trip through Qt's untyped item data.
        self._ids: list[str] = []
        self.setItemDelegate(StepRowDelegate(self))
        self.setWordWrap(False)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def show_steps(self, rows: list[tuple[str, str, str]]) -> None:
        """``(step id, title, secondary)``, in order."""
        self.clear()
        self._ids = [step_id for step_id, _title, _secondary in rows]
        for _step_id, title, secondary in rows:
            item = QListWidgetItem(title)
            item.setData(SECONDARY_ROLE, secondary)
            self.addItem(item)

    def step_id_at(self, row: int) -> str | None:
        return self._ids[row] if 0 <= row < len(self._ids) else None

    def selected_step_id(self) -> str | None:
        return self.step_id_at(self.currentRow())
