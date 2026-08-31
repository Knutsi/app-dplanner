"""The order view's table: one row per step, in the order the work can be done.

A table rather than a nested list, because the thing being shown *is* a sorted sequence and
the first thing you want from one is a position. The wave rides along as a column: two steps
sharing a wave can be started together, and the first wave is the answer to "what now".

The schedule columns come from ``domain/schedule.py`` and are rendered with its own
formatter, so this table and ``dplanner schedule show`` cannot express one number two ways.

Rebuilt whenever the graph changes. A project holds tens of steps, so a whole redraw is
cheaper to read than a diff and cannot go stale.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.schedule import Scheduled, format_date, format_days
from dplanner.modules.step_order.export import since_milestone
from dplanner.theme.icons import spark_icon, tag_icon

COLUMNS = ("#", "Step", "Wave", "Estimate", "Accumulated", "Since milestone", "Date", "")
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ACCUMULATED_COLUMN = 4
SINCE_MILESTONE_COLUMN = 5
DATE_COLUMN = 6
ASPECTS_COLUMN = 7

# Numbers line up on the right; everything else — headers included (DESIGN.md's *Tables*) —
# reads from the left.
NUMERIC_COLUMNS = (ESTIMATE_COLUMN, ACCUMULATED_COLUMN, SINCE_MILESTONE_COLUMN)

# The step id on a row, so a click can say which step it means.
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 1
# The milestone label on every cell of a milestone row, so the delegate can mark it from any
# column's index. Falsy on ordinary rows.
MILESTONE_ROLE = int(Qt.ItemDataRole.UserRole) + 2

# DESIGN.md's row metrics for a list of rich items; a milestone row gets air under its rule.
ROW_HEIGHT = 28
MILESTONE_ROW_EXTRA = 8

# A milestone's own answers grow a point instead of going bold: emphasis without the weight
# a bold row puts on a table of mostly-quiet lines.
MILESTONE_POINT_INCREMENT = 1.0

# The milestone row's marks: the canvas badge's purple family, low-alpha so it reads on every
# theme (DESIGN.md exception #2). The rule closes the block of work that lands in it.
MILESTONE_ROW_TINT = QColor(150, 130, 220, 22)
MILESTONE_RULE = QColor(150, 130, 220, 160)
# The tag icon at full strength — a glyph this small needs its whole ink to read.
MILESTONE_ICON_INK = QColor(150, 130, 220)

# Secondary text as opacity rather than a theme colour: an item has only the palette, and an
# alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class _MilestoneRowDelegate(QStyledItemDelegate):
    """Marks a milestone row: a low-alpha tint under it and a rule along its bottom.

    The grid is off, so each cell's bottom segment joins into the one horizontal line in
    the table — "everything above this lands in the milestone". The flag is read off the
    index (``MILESTONE_ROLE``), never asked of a callback, so painting stays a pure function
    of the model.
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not index.data(MILESTONE_ROLE):
            super().paint(painter, option, index)
            return
        painter.fillRect(option.rect, MILESTONE_ROW_TINT)
        super().paint(painter, option, index)  # Text and selection paint over the tint.
        painter.save()
        painter.setPen(QPen(MILESTONE_RULE, 1.0))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


class OrderTable(QTableWidget):
    """Steps in topological order: index, name, wave, what they cost, when they land."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        milestone_label: Callable[[StepId], str] = lambda _step_id: "",
        step_icons: Callable[[StepId], tuple[str, ...]] = lambda _step_id: (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setObjectName("OrderTable")
        self._wave_label = wave_label
        self._step_aspects = step_aspects
        self._milestone_label = milestone_label
        self._step_icons = step_icons
        self.setItemDelegate(_MilestoneRowDelegate(self))

        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)

        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in range(len(COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Interactive
                if column == TITLE_COLUMN
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)
        # The last column takes the slack, so the aspects have room and nothing else moves.
        header.setStretchLastSection(True)
        header.setHighlightSections(False)

    def show_order(self, order: Sequence[Scheduled]) -> None:
        selected = self.selected_step()
        spans = since_milestone(order, self._milestone_label)
        self.setRowCount(len(order))
        for row, scheduled in enumerate(order):
            place = scheduled.place
            span = spans.get(place.step.id)
            cells = (
                str(place.index),
                place.step.title or "Untitled step",
                self._wave_label(place.wave - 1),
                format_days(scheduled.days),
                format_days(scheduled.accumulated),
                format_days(span) if span is not None else "",
                format_date(scheduled.finish) if scheduled.finish else "",
                " · ".join(self._step_aspects(place.step.id)),
            )
            milestone = self._milestone_label(place.step.id)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(STEP_ROLE, place.step.id)
                item.setData(MILESTONE_ROLE, milestone)
                # A milestone's own answers — its name, the span it closes, its date — read a
                # point larger at full strength; the foreground is deliberately not set, so
                # it stays the palette's and live.
                highlighted = bool(milestone) and column in (
                    TITLE_COLUMN,
                    SINCE_MILESTONE_COLUMN,
                    DATE_COLUMN,
                )
                if column != TITLE_COLUMN and not highlighted:
                    faded = self.palette().text().color()
                    faded.setAlpha(SECONDARY_ALPHA)
                    item.setForeground(faded)
                if highlighted:
                    font = item.font()
                    if font.pointSizeF() > 0:
                        font.setPointSizeF(font.pointSizeF() + MILESTONE_POINT_INCREMENT)
                    item.setFont(font)
                if column == TITLE_COLUMN:
                    icon = self._title_icon(self._step_icons(place.step.id))
                    if icon is not None:
                        item.setIcon(icon)
                if column in NUMERIC_COLUMNS:
                    item.setTextAlignment(_RIGHT)
                self.setItem(row, column, item)
            self.setRowHeight(row, ROW_HEIGHT + (MILESTONE_ROW_EXTRA if milestone else 0))
        # A column of blanks says less than an absent one: nothing estimated, no Date column;
        # no milestone to measure to (or no days to measure with), no Since-milestone column.
        undated = all(s.finish is None for s in order)
        self.setColumnHidden(DATE_COLUMN, undated)
        self.setColumnHidden(SINCE_MILESTONE_COLUMN, undated or not spans)
        self.resizeColumnToContents(TITLE_COLUMN)
        if selected is not None:
            self.select_step(selected)

    def _title_icon(self, kinds: tuple[str, ...]) -> QIcon | None:
        """The first kind's glyph, in the canvas medallions' vocabulary; a plain step has none.

        One icon per row: a step that is several things at once leads with the rarer claim
        ("tag" sorts first), and the trailing aspects column still says the rest.
        """
        for kind in kinds:
            if kind == "tag":
                return tag_icon(MILESTONE_ICON_INK)
            if kind == "spark":
                faded = QColor(self.palette().text().color())
                faded.setAlpha(SECONDARY_ALPHA)
                return spark_icon(faded)
        return None

    def step_at(self, row: int) -> StepId | None:
        item = self.item(row, 0)
        if item is None:
            return None
        found = item.data(STEP_ROLE)
        return found if isinstance(found, str) else None

    def selected_step(self) -> StepId | None:
        return self.step_at(self.currentRow()) if self.currentRow() >= 0 else None

    def select_step(self, step_id: StepId) -> None:
        for row in range(self.rowCount()):
            if self.step_at(row) == step_id:
                self.selectRow(row)
                return
