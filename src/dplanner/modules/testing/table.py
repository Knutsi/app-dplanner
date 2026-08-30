"""The tests table: one widget, two scopes.

The project's Tests tab and the library-wide roster show the same rows with the same
columns; the only difference is where the rows came from and whether a project column is
worth printing. Writing that once is the difference between a feature and two features that
will drift — and the cross-project view is explicitly the half that grows later.

Column conventions follow ``step_order``'s table verbatim, including the two that are easy
to forget: **headers are left-aligned whatever the column holds**, and **a column of blanks
is hidden rather than shown**.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.domain.model import Step, StepId
from dplanner.modules.testing.aspect import Test
from dplanner.modules.testing.runs import Outcome
from dplanner.modules.testing.view import (
    ROW_HEIGHT,
    SECONDARY_ALPHA,
    TestRowDelegate,
    tint,
    word,
)

COLUMNS = ("Test", "Project", "Step", "Covered by", "Result", "When")
TEST_COLUMN, PROJECT_COLUMN, STEP_COLUMN, COVERED_COLUMN, RESULT_COLUMN, WHEN_COLUMN = range(6)

# A test's own line can be long; past this the column stops growing and elides.
TEST_MAX_WIDTH = 340

TEST_ROLE = int(Qt.ItemDataRole.UserRole) + 1
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 2


@dataclass(frozen=True)
class Row:
    """One test, with everything a reader needs about it already resolved.

    The table is handed rows rather than a model to walk, so the same widget serves a
    project and a whole library without learning the difference between them.
    """

    test: Test
    step: Step
    project: str = ""
    covered_by: tuple[str, ...] = ()
    outcome: Outcome | None = None
    status: str = "pending"  # This run's result in run mode; the latest one otherwise.


class TestsTable(QTableWidget):
    """Every test in scope: what it checks, whose step it is, and how it did."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setObjectName("OrderTable")  # The one table look in this application.
        self._sized = False
        self.setItemDelegate(TestRowDelegate(self))

        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        # A table takes its row height from the header, not from the delegate's hint;
        # without this the second line prints over the row below it.
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Extended, because marking twelve tests at once is the gesture a run is made of.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)

        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in range(len(COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Interactive
                if column == TEST_COLUMN
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)

    def show_rows(self, rows: Sequence[Row], *, show_project: bool = False) -> None:
        keep = self.selected_tests()
        self.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self._fill(index, row)
        # A column of blanks is noise: hide what this scope has nothing to say about.
        self.setColumnHidden(PROJECT_COLUMN, not show_project)
        self.setColumnHidden(COVERED_COLUMN, not any(row.covered_by for row in rows))
        self.setColumnHidden(WHEN_COLUMN, not any(row.outcome for row in rows))
        self._reselect(keep)
        if not self._sized:
            # Once, on the first rows: the test column is Interactive so the user's own
            # width survives every refresh after this one.
            self.resizeColumnToContents(TEST_COLUMN)
            self.setColumnWidth(TEST_COLUMN, min(self.columnWidth(TEST_COLUMN), TEST_MAX_WIDTH))
            self._sized = bool(rows)

    def _fill(self, index: int, row: Row) -> None:
        first_line = row.test.body.strip().splitlines()[0] if row.test.body.strip() else ""
        cells = (
            row.test.title or "Untitled test",
            row.project,
            row.step.title or "Untitled step",
            ", ".join(row.covered_by),
            word(row.status),
            _when(row),
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setData(TEST_ROLE, row.test.id)
            item.setData(STEP_ROLE, row.step.id)
            item.setData(TestRowDelegate.FAILED_ROLE, row.status == "failed")
            if column == TEST_COLUMN:
                item.setData(TestRowDelegate.SECONDARY_ROLE, first_line)
            elif column == RESULT_COLUMN:
                # The one place a colour is asserted: a status means the same on every
                # theme, so this is a constant rather than a palette field (DESIGN.md #2).
                colour = tint(row.status)
                if colour is not None:
                    item.setForeground(colour)
            else:
                faded = self.palette().text().color()
                faded.setAlpha(SECONDARY_ALPHA)
                item.setForeground(faded)
            if row.test.archived:
                item.setToolTip("Archived — off the roster and out of new runs")
            self.setItem(index, column, item)

    def test_at(self, row: int) -> str | None:
        item = self.item(row, TEST_COLUMN)
        return None if item is None else str(item.data(TEST_ROLE))

    def step_at(self, row: int) -> StepId | None:
        item = self.item(row, TEST_COLUMN)
        return None if item is None else str(item.data(STEP_ROLE))

    def selected_tests(self) -> list[str]:
        return [
            found
            for row in sorted({index.row() for index in self.selectedIndexes()})
            if (found := self.test_at(row)) is not None
        ]

    def selected_steps(self) -> list[StepId]:
        return [
            found
            for row in sorted({index.row() for index in self.selectedIndexes()})
            if (found := self.step_at(row)) is not None
        ]

    def _reselect(self, test_ids: Sequence[str]) -> None:
        """Keep the selection across a rebuild, by test id — the rows are new objects.

        Selected through the selection model rather than ``selectRow``, which replaces the
        selection rather than adding to it and would leave only the last row picked.
        """
        if not test_ids:
            return
        wanted = set(test_ids)
        model = self.selectionModel()
        self.clearSelection()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in range(self.rowCount()):
            if self.test_at(row) in wanted:
                model.select(self.model().index(row, TEST_COLUMN), flags)


def _when(row: Row) -> str:
    if row.outcome is None:
        return ""
    label = row.outcome.run.label or row.outcome.run.id
    stamp = row.outcome.run.closed or row.outcome.run.opened
    return f"{label} · {stamp[:10]}" if stamp else label
