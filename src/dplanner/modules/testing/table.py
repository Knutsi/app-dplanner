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
from dplanner.theme.tones import recoloured

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
    # What this test is filed under when the reader asked for grouping — a feature's title,
    # or the fallback for one nothing gathers. Empty on every row means no grouping, and
    # the table draws no headings at all. Whoever orders the rows also fills this in:
    # rows of one group must arrive together, and there is one place that orders them.
    group: str = ""
    # The heading's own colour when the group is a milestone: its shade of the project's
    # colour map. "" for a feature heading and for the ungathered fallback — a feature is
    # not dealt a shade, and nothing is not a thing.
    group_color: str = ""


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
        laid = _with_headings(rows)
        self.clearSpans()
        self.setRowCount(len(laid))
        for index, entry in enumerate(laid):
            if isinstance(entry, tuple):
                self._fill_heading(index, *entry)
            else:
                self._fill(index, entry)
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

    def _fill_heading(self, index: int, title: str, color: str = "") -> None:
        """A group's name, spanning the table: not a row, and never selectable.

        Left out of the delegate's two-line treatment on purpose — a heading is one line,
        and a second line under it would read as a test that cannot be marked.

        A milestone heading is written in the milestone's own shade of the project's colour
        map rather than the secondary ink every other heading takes, so grouping by
        milestone reads as the same sequence the calendar and the graph show. It stays the
        heading's weight and size: colour is the only thing that changes.
        """
        item = QTableWidgetItem(title)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        faded = self.palette().text().color()
        faded.setAlpha(SECONDARY_ALPHA)
        item.setForeground(recoloured(faded, color) if color else faded)
        self.setItem(index, TEST_COLUMN, item)
        for column in range(1, len(COLUMNS)):
            blank = QTableWidgetItem("")
            blank.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(index, column, blank)
        self.setSpan(index, TEST_COLUMN, 1, len(COLUMNS))

    def _fill(self, index: int, row: Row) -> None:
        first_line = _preview(row.test.body)
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
        # A group heading is a real row carrying no test, so an unset role has to answer
        # None rather than the string "None" — which is what a bare str() would hand back.
        return _role_at(self.item(row, TEST_COLUMN), TEST_ROLE)

    def step_at(self, row: int) -> StepId | None:
        return _role_at(self.item(row, TEST_COLUMN), STEP_ROLE)

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


def _role_at(item: QTableWidgetItem | None, role: int) -> str | None:
    if item is None:
        return None
    found = item.data(role)
    return str(found) if found is not None else None


def _with_headings(rows: Sequence[Row]) -> list[Row | tuple[str, str]]:
    """The rows with a heading wherever the group changes; unchanged when nothing groups.

    A heading is ``(title, colour)`` — the colour is the first row's, since every row of a
    group names the same collector.
    """
    if not any(row.group for row in rows):
        return list(rows)
    laid: list[Row | tuple[str, str]] = []
    current = None
    for row in rows:
        if row.group != current:
            current = row.group
            laid.append((current, row.group_color))
        laid.append(row)
    return laid


def _preview(body: str) -> str:
    """The first content line, read as prose: markdown markers are source, not preview."""
    for line in body.splitlines():
        text = line.strip().lstrip("#>*- ").strip()
        if text:
            return text
    return ""


def _when(row: Row) -> str:
    if row.outcome is None:
        return ""
    label = row.outcome.run.label or row.outcome.run.id
    stamp = row.outcome.run.closed or row.outcome.run.opened
    return f"{label} · {stamp[:10]}" if stamp else label
