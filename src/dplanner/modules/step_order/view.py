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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.schedule import Scheduled, format_days

COLUMNS = ("#", "Step", "Wave", "Estimate", "Accumulated", "Date", "")
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ACCUMULATED_COLUMN = 4
DATE_COLUMN = 5
ASPECTS_COLUMN = 6

# Numbers line up on the right; everything else reads from the left.
NUMERIC_COLUMNS = (ESTIMATE_COLUMN, ACCUMULATED_COLUMN)

# The step id on a row, so a click can say which step it means.
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 1

# DESIGN.md's row metrics for a list of rich items.
ROW_HEIGHT = 28

# Secondary text as opacity rather than a theme colour: an item has only the palette, and an
# alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class OrderTable(QTableWidget):
    """Steps in topological order: index, name, wave, what they cost, when they land."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setObjectName("OrderTable")
        self._wave_label = wave_label
        self._step_aspects = step_aspects

        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)

        header = self.horizontalHeader()
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
        self.setRowCount(len(order))
        for row, scheduled in enumerate(order):
            place = scheduled.place
            cells = (
                str(place.index),
                place.step.title or "Untitled step",
                self._wave_label(place.wave - 1),
                format_days(scheduled.days),
                format_days(scheduled.accumulated),
                scheduled.finish.isoformat() if scheduled.finish else "",
                " · ".join(self._step_aspects(place.step.id)),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(STEP_ROLE, place.step.id)
                if column != TITLE_COLUMN:
                    faded = self.palette().text().color()
                    faded.setAlpha(SECONDARY_ALPHA)
                    item.setForeground(faded)
                if column in NUMERIC_COLUMNS:
                    item.setTextAlignment(_RIGHT)
                self.setItem(row, column, item)
            self.setRowHeight(row, ROW_HEIGHT)
        # A column of blanks says less than an absent one: no start date, no Date column.
        self.setColumnHidden(DATE_COLUMN, all(s.finish is None for s in order))
        self.resizeColumnToContents(TITLE_COLUMN)
        if selected is not None:
            self.select_step(selected)

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
