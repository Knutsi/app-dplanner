"""The Tests tab's bottom pane: where the picked test came from.

A test is a claim about the product, and *which* claim is the first thing a tester needs
and the last thing a roster usually says. The Sources column says how many and what they
are called; this pane, under the table, says all of them at once — a row each, what it
says beside it, and a double-click that opens the spec document or the note it points at.

**The quote is in the row and in the tooltip.** A passage is often a paragraph, and a
table cell elides: the cell shows as much as fits and the tooltip carries the whole of
it, wrapped (``wrapped_tooltip`` — Qt lays a plain tooltip on one endless line).

**A source that is no longer there still shows.** A renamed document or a deleted note
leaves a pointer nobody can follow, and hiding it would leave the test looking sourced.
The row says so and the double-click is refused, which is how a reader finds out there is
something to mend.
"""

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.widgets import caption, note, wrapped_tooltip
from dplanner.modules.testing.aspect import (
    NOTE_SOURCE,
    SourceFacts,
    Test,
    TestSource,
)
from dplanner.theme.tokens import CAPTION_GAP

SOURCE_ROLE = HOST_ROLE

PANE_CAPTION = "Where this test came from"
COLUMNS = (
    Column("Source", detail=True, resize="interactive"),
    Column("What it says", resize="stretch"),
)
SOURCE_COLUMN, SAYS_COLUMN = range(2)
SOURCE_WIDTH = 260

KIND_WORDS = {NOTE_SOURCE: "Implementation note"}
SPEC_WORDS = "Specification"
GONE = " — no longer there"
NOTHING_PICKED = "Pick a test to see where it came from."
# Short on purpose: this pane is a quarter of the tab's height and the sentence has to be
# read whole. Why it matters is ARCHITECTURE.md's; what to do about it is the second line.
UNSOURCED = (
    "This test says nowhere it came from, so nobody can judge what it is really asking.\n"
    "Cite the spec passage it proves, or the note it came out of: "
    "dplanner test cite <test> --document <doc> --quote '…'  |  --note N<n>"
)

# The resolver the pane is handed: a source in, what it is called and what it says out.
FactsFor = Callable[[TestSource], SourceFacts]


def kind_words(source: TestSource) -> str:
    return KIND_WORDS.get(source.kind, SPEC_WORDS)


class SourcesPane(QWidget):
    """A caption, then the picked test's sources — or one sentence saying there are none."""

    def __init__(self, open_source: Callable[[TestSource], None], parent: QWidget | None = None):
        super().__init__(parent)
        self._open = open_source
        self._sources: list[TestSource] = []

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CAPTION_GAP)
        column.addWidget(caption(PANE_CAPTION, self))
        self.table = Table(COLUMNS, selection="single", parent=self)
        self.table.cellActivated.connect(self._on_activated)
        column.addWidget(self.table, 1)
        self.empty = note("", self)
        column.addWidget(self.empty, 1)

    def show_sources(self, test: Test | None, facts_for: FactsFor) -> None:
        """The picked test's sources — nothing picked and no sources both say so in words."""
        self._sources = list(test.sources) if test is not None else []
        self.table.clear_rows()
        for source in self._sources:
            facts = facts_for(source)
            tip = wrapped_tooltip(facts.detail)
            self.table.add_row(
                (
                    Cell(
                        facts.label + ("" if facts.found else GONE),
                        detail=kind_words(source),
                        secondary=not facts.found,
                        tooltip=tip,
                    ),
                    Cell(_one_line(facts.detail), secondary=True, tooltip=tip),
                ),
                data={SOURCE_ROLE: source.ref},
            )
        message = "" if self._sources else (NOTHING_PICKED if test is None else UNSOURCED)
        self.empty.setText(message)
        self.empty.setVisible(bool(message))
        self.table.setVisible(not message)
        if self._sources:
            self.table.setColumnWidth(SOURCE_COLUMN, SOURCE_WIDTH)

    def sources(self) -> Sequence[TestSource]:
        """What the pane is showing — what a test reads instead of walking the rows."""
        return tuple(self._sources)

    def _on_activated(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._sources):
            self._open(self._sources[row])


def _one_line(text: str) -> str:
    """The passage as one line: a cell is one line high, and the tooltip has the rest."""
    return " ".join(text.split())
