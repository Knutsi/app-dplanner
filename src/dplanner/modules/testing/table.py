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

**Seven columns, because a roster is read down a column and not across one.** What a test
checks, **its id**, what it is filed under and in what order, who it is for, and how it did.
Three columns were taken out rather than narrowed: *Covered by* named the collectors behind
a test, which is the Covers tab's whole subject and was a comma-separated list nobody
compared down the page; *When* dated the last run, which is exactly the fact a test outlives
— these are kept and re-run long after the step that added them shipped, so the run that
last touched one says little about whether it still holds; and *Step* gave up its seat to
the id. All three are one click away, in the Test panel and in ``dplanner test show``.

**The id is a column because a test body quotes one.** A test that says *after T101 passes*
is pointing somewhere, and until this column existed the roster printed every fact about a
test except the one word it is called by — so the reader had to open tests until they found
the right one. The Test panel's *Show Step* is the door to whose step a test is, which is
what this column was before, and the step is still on the panel's filed line.

**A category heading folds.** Grouped by category the headings are collapsible, because
that is the reading the grouping is for: two hundred tests become a dozen lines, and you
open the one you are working on. The table primitive owns the mechanics and remembers what
is shut by key, so a rebuild between two keystrokes does not spring every group open.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QItemSelectionModel
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from dplanner.domain.model import Step, StepId
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Selection, Table
from dplanner.modules.testing.aspect import Test, audience_words
from dplanner.modules.testing.filing import category_of
from dplanner.modules.testing.view import FAILED_ROW_TINT, tint, word
from dplanner.theme.icons import glyph_icon
from dplanner.theme.tokens import SECONDARY_ALPHA

COLUMNS = (
    Column("Test", detail=True, resize="interactive"),
    Column("Project"),
    Column("Id"),
    Column("Category"),
    Column("Sort key"),
    Column("Audience"),
    Column("Result"),
)
(
    TEST_COLUMN,
    PROJECT_COLUMN,
    ID_COLUMN,
    CATEGORY_COLUMN,
    SORT_KEY_COLUMN,
    AUDIENCE_COLUMN,
    RESULT_COLUMN,
) = range(7)

# A test's own line can be long; past this the column stops growing and elides.
TEST_MAX_WIDTH = 340

TEST_ROLE = HOST_ROLE
STEP_ROLE = HOST_ROLE + 1

ARCHIVED_TIP = "Archived — off the roster and out of new runs"


@dataclass(frozen=True)
class Heading:
    """One group's spanned row: what it says, and how it is drawn.

    ``key`` is what the table folds by — a category's name — and "" is a heading that does
    not fold, which is what grouping by feature or milestone still draws. ``glyph`` is the
    group's own picture, ``ink`` a milestone's shade.
    """

    title: str = ""  # Empty is *no heading*: a flat list gives every row one of these.
    key: str = ""
    ink: str = ""
    glyph: str = ""


@dataclass(frozen=True)
class Row:
    """One test, with everything a reader needs about it already resolved.

    The table is handed rows rather than a model to walk, so the same widget serves a
    project and a whole library without learning the difference between them.
    """

    test: Test
    step: Step
    project: str = ""
    status: str = "pending"  # This run's result in run mode; the latest one otherwise.
    # What this test is filed under when the reader asked for grouping — a category's name,
    # a feature's title, or the fallback for one nothing gathers. Empty on every row means
    # no grouping, and the table draws no headings at all. Whoever orders the rows also
    # fills this in: rows of one group must arrive together, and there is one place that
    # orders them.
    heading: Heading = field(default_factory=Heading)


class TestsTable(Table):
    """Every test in scope: what it checks, what it is called, and how it did."""

    def __init__(self, parent: QWidget | None = None, *, selection: Selection = "extended") -> None:
        # Extended on the project tab, because marking twelve tests at once is the gesture a
        # run is made of.
        super().__init__(COLUMNS, selection=selection, parent=parent)
        self._sized = False
        # What it was last shown, so a palette change can draw the headings' glyphs again
        # in the new ink — a colour taken out of the palette goes stale (``CLAUDE.md``).
        self._shown: tuple[Sequence[Row], bool, bool] = ((), False, True)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """The headings' glyphs again, in the new theme's ink.

        ``getattr``, not a plain read: Qt delivers a PaletteChange from inside
        ``QTableWidget.__init__``, before this class's own state exists.
        """
        shown = getattr(self, "_shown", None)
        if event.type() == QEvent.Type.PaletteChange and shown is not None and shown[0]:
            self.show_rows(shown[0], show_project=shown[1], show_category=shown[2])
        super().changeEvent(event)

    def show_rows(
        self,
        rows: Sequence[Row],
        *,
        show_project: bool = False,
        show_category: bool = True,
    ) -> None:
        self._shown = (list(rows), show_project, show_category)
        keep = self.selected_tests()
        self.clear_rows()
        for entry in _with_headings(rows):
            if isinstance(entry, Row):
                self._add(entry)
            else:
                self.add_heading(
                    entry.title,
                    ink=_shade(entry.ink),
                    glyph=self._glyph(entry.glyph),
                    key=entry.key,
                )
        # A column of blanks is noise: hide what this scope has nothing to say about.
        self.setColumnHidden(PROJECT_COLUMN, not show_project)
        # And a column that repeats the heading over every row under it is noise twice: the
        # category column stands down while the rows are already filed by category.
        self.setColumnHidden(
            CATEGORY_COLUMN, not show_category or not any(row.test.category for row in rows)
        )
        self.setColumnHidden(SORT_KEY_COLUMN, not any(row.test.sort_key for row in rows))
        # On the test's *stored* audiences, not on what it reads as: `audience_words` never
        # answers blank, so a project nobody has classified would otherwise grow a column
        # saying "Other" all the way down.
        self.setColumnHidden(AUDIENCE_COLUMN, not any(row.test.audiences for row in rows))
        self._reselect(keep)
        if not self._sized:
            # Once, on the first rows: the test column is interactive so the reader's own
            # width survives every refresh after this one.
            self.fit_columns()
            self.setColumnWidth(TEST_COLUMN, min(self.columnWidth(TEST_COLUMN), TEST_MAX_WIDTH))
            self._sized = bool(rows)

    def _glyph(self, name: str) -> QIcon | None:
        """A heading's glyph in the strip's own tone, painted now — see ``changeEvent``."""
        if not name:
            return None
        ink = self.palette().color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        return glyph_icon(name, ink)

    def _add(self, row: Row) -> None:
        tip = ARCHIVED_TIP if row.test.archived else ""
        self.add_row(
            (
                Cell(
                    row.test.title or "Untitled test", detail=_preview(row.test.body), tooltip=tip
                ),
                Cell(row.project, secondary=True, tooltip=tip),
                # The id a reader has to be able to find: a body quoting *T101* is a
                # reference to somewhere, and this is the column they look down for it.
                Cell(row.test.id, secondary=True, tooltip=tip),
                # What it *reads* as, so an unfiled test says so rather than showing a hole.
                Cell(category_of(row.test), secondary=True, tooltip=tip),
                # The stored key, which is blank for most tests and is the point of the
                # blank-column rule: the column appears the day a project starts using one.
                Cell(row.test.sort_key, secondary=True, tooltip=tip),
                Cell(audience_words(row.test), secondary=True, tooltip=tip),
                # The one place a colour is asserted: a status means the same on every theme.
                Cell(word(row.status), ink=tint(row.status), tooltip=tip),
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

    def tests_under(self, row: int) -> list[str]:
        """Every test filed under the heading at ``row`` — what a right-click there acts on.

        A heading names a group and a group is a set of tests, so making the thing under
        the cursor current means selecting them, which is what lets the Step menu's verbs
        act on a whole category without a verb of their own.
        """
        key = self.group_at(row)
        if not key:
            return []
        found = []
        for below in range(row + 1, self.rowCount()):
            if self.is_heading(below):
                break  # The next heading: the group ends here.
            if (test_id := self.test_at(below)) is not None:
                found.append(test_id)
        return found

    def select_tests(self, test_ids: Sequence[str]) -> None:
        """Pick exactly these tests, by id — a rebuild's rows are new objects."""
        self._reselect(test_ids)

    def reveal(self, test_id: str) -> None:
        """Bring one test's row on screen: open the group it is under, and scroll to it.

        Deliberately not part of ``select_tests``, which runs on every rebuild to keep the
        selection: unfolding there would spring a group open again the moment the reader
        shut one holding the row they had picked.
        """
        row = next(
            (found for found in range(self.rowCount()) if self.test_at(found) == test_id), None
        )
        if row is None:
            return
        if key := self.group_of(row):
            self.set_collapsed(key, False)
        if (item := self.item(row, TEST_COLUMN)) is not None:
            self.scrollToItem(item)

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


def _with_headings(rows: Sequence[Row]) -> list[Row | Heading]:
    """The rows with a heading wherever the group changes; unchanged when nothing groups.

    The heading is the first row's — every row of a group carries the same one.
    """
    if not any(row.heading.title for row in rows):
        return list(rows)
    laid: list[Row | Heading] = []
    current: str | None = None
    for row in rows:
        if row.heading.title != current:
            current = row.heading.title
            laid.append(row.heading)
        laid.append(row)
    return laid


def _preview(body: str) -> str:
    """The first content line, read as prose: markdown markers are source, not preview."""
    for line in body.splitlines():
        text = line.strip().lstrip("#>*- ").strip()
        if text:
            return text
    return ""
