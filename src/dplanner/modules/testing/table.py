"""The tests table: one widget, two scopes, on the table primitive.

The project's Tests tab and the library-wide roll call show the same rows with the same
columns; the only difference is where the rows came from and whether a project column is
worth printing. Writing that once is the difference between a feature and two features that
will drift — and the cross-project view is explicitly the half that grows later.

What a row wears is ``framework/table.py``'s: the test's title over the first line of its
body, the result in its own tone, a failed row washed in the failure's, and a group as one
spanned heading — written in a milestone's shade when the group is a milestone, so grouping
by milestone reads as the same sequence the calendar and the graph show. **A column of
blanks is hidden rather than shown.**
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from dplanner.domain.model import Step, StepId
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Selection, Table
from dplanner.modules.testing.aspect import Test, audience_words
from dplanner.modules.testing.runs import Outcome
from dplanner.modules.testing.view import FAILED_ROW_TINT, tint, word
from dplanner.theme.tokens import SECONDARY_ALPHA

COLUMNS = (
    Column("Test", detail=True, resize="interactive"),
    Column("Project"),
    Column("Step"),
    Column("Covered by"),
    Column("Audience"),
    Column("Result"),
    Column("When"),
)
(
    TEST_COLUMN,
    PROJECT_COLUMN,
    STEP_COLUMN,
    COVERED_COLUMN,
    AUDIENCE_COLUMN,
    RESULT_COLUMN,
    WHEN_COLUMN,
) = range(7)

# A test's own line can be long; past this the column stops growing and elides.
TEST_MAX_WIDTH = 340

TEST_ROLE = HOST_ROLE
STEP_ROLE = HOST_ROLE + 1

ARCHIVED_TIP = "Archived — off the roster and out of new runs"


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


class TestsTable(Table):
    """Every test in scope: what it checks, whose step it is, and how it did."""

    def __init__(self, parent: QWidget | None = None, *, selection: Selection = "extended") -> None:
        # Extended on the project tab, because marking twelve tests at once is the gesture a
        # run is made of.
        super().__init__(COLUMNS, selection=selection, parent=parent)
        self._sized = False

    def show_rows(self, rows: Sequence[Row], *, show_project: bool = False) -> None:
        keep = self.selected_tests()
        self.clear_rows()
        for entry in _with_headings(rows):
            if isinstance(entry, Row):
                self._add(entry)
            else:
                title, color = entry
                self.add_heading(title, ink=_shade(color))
        # A column of blanks is noise: hide what this scope has nothing to say about.
        self.setColumnHidden(PROJECT_COLUMN, not show_project)
        self.setColumnHidden(COVERED_COLUMN, not any(row.covered_by for row in rows))
        # On the test's *stored* audiences, not on what it reads as: `audience_words` never
        # answers blank, so a project nobody has classified would otherwise grow a column
        # saying "Other" all the way down.
        self.setColumnHidden(AUDIENCE_COLUMN, not any(row.test.audiences for row in rows))
        self.setColumnHidden(WHEN_COLUMN, not any(row.outcome for row in rows))
        self._reselect(keep)
        if not self._sized:
            # Once, on the first rows: the test column is interactive so the reader's own
            # width survives every refresh after this one.
            self.fit_columns()
            self.setColumnWidth(TEST_COLUMN, min(self.columnWidth(TEST_COLUMN), TEST_MAX_WIDTH))
            self._sized = bool(rows)

    def _add(self, row: Row) -> None:
        tip = ARCHIVED_TIP if row.test.archived else ""
        self.add_row(
            (
                Cell(
                    row.test.title or "Untitled test", detail=_preview(row.test.body), tooltip=tip
                ),
                Cell(row.project, secondary=True, tooltip=tip),
                Cell(row.step.title or "Untitled step", secondary=True, tooltip=tip),
                Cell(", ".join(row.covered_by), secondary=True, tooltip=tip),
                Cell(audience_words(row.test), secondary=True, tooltip=tip),
                # The one place a colour is asserted: a status means the same on every theme.
                Cell(word(row.status), ink=tint(row.status), tooltip=tip),
                Cell(_when(row), secondary=True, tooltip=tip),
            ),
            tint=FAILED_ROW_TINT if row.status == "failed" else None,
            data={TEST_ROLE: row.test.id, STEP_ROLE: row.step.id},
        )

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


def _shade(color: str) -> QColor | None:
    """A milestone heading's ink: its shade at the secondary alpha every heading's words take."""
    if not color:
        return None
    ink = QColor(color)
    ink.setAlpha(SECONDARY_ALPHA)
    return ink


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
