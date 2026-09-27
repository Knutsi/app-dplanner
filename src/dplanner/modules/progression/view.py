"""The Step statuses table: what needs a person right now, grouped, a box on every row.

Pure rendering — the domain's :class:`~dplanner.domain.progression.Progression` arrives
computed and the table is rebuilt wholesale, so nothing here can disagree with the model.
The groups are the partitions a person acts on, in the order they are closest to done —
Blocked, Ready to merge, Ready for review, Ready to start — and then Waiting, what cannot
start yet. Work in progress is not listed: an agent at work needs nobody, and the board is
for the rows that do.

**The box is the selection.** The first column is a check column (``Column(check=True)``):
ticking a row picks it, and the host publishes what is picked, so the strip's verbs, the
right-click Step menu and Run Agent's profiles all act on exactly the ticked rows. The
picks survive a rebuild by step id — an accepted review is still ticked in its new group.

A row's glyph is what the step is — a milestone's key as a badge in its own shade, the
canvas medallion otherwise — painted in the palette's ink, so a palette change paints the
rows again (``changeEvent``): a colour taken out of the palette goes stale.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QItemSelectionModel
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Step, StepId
from dplanner.domain.progression import Progression
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Table
from dplanner.theme.icons import glyph_painter, step_icon
from dplanner.theme.tokens import SECONDARY_ALPHA

STEP_ROLE = HOST_ROLE
CHECK_COLUMN, STEP_COLUMN, UNBLOCKS_COLUMN = range(3)
COLUMNS = (
    Column("", check=True),
    Column("Step", glyph=True, detail=True, resize="stretch"),
    Column("Unblocks", numeric=True),
)

ALL = "all"


@dataclass(frozen=True)
class Group:
    """One kind of row: its key (the filter's value and the heading's fold), the heading's
    words, the filter's word, and what the table says when it is the only one and empty."""

    key: str
    heading: str
    label: str
    empty: str


GROUPS = (
    Group("blocked", "Blocked", "Blocked", "Nothing is blocked."),
    Group("merge", "Ready to merge", "Merge", "Nothing is waiting on a merge."),
    Group("review", "Ready for review", "Review", "Nothing is ready for review."),
    Group("start", "Ready to start", "Start", "Nothing is ready to start."),
    Group("waiting", "Waiting", "Waiting", "Nothing is waiting."),
)
# What needs a person: everything but Waiting, which is the rest of the plan.
ATTENTION = ("blocked", "merge", "review", "start")


def grouped(progress: Progression) -> dict[str, tuple[Step, ...]]:
    """Each group's steps, in the order the derivation ranked them."""
    return {
        "blocked": progress.attention,
        "merge": progress.merge,
        "review": progress.review,
        "start": progress.ready,
        "waiting": (*(coming.step for coming in progress.upcoming), *progress.waiting),
    }


def needing_attention(progress: Progression) -> int:
    rows = grouped(progress)
    return sum(len(rows[key]) for key in ATTENTION)


class StatusTable(Table):
    """The rows, grouped; ``show_rows`` rebuilds them for one filter."""

    def __init__(
        self,
        *,
        key_of: Callable[[Step], str],
        glyph_of: Callable[[Step], str],
        milestone_badge: Callable[[StepId], QIcon | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(COLUMNS, selection="extended", parent=parent)
        self._key_of = key_of
        self._glyph_of = glyph_of
        self._milestone_badge = milestone_badge
        self._shown: tuple[Progression, str] | None = None

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """The glyphs again, in the new theme's ink.

        ``getattr``, not a plain read: Qt delivers a PaletteChange from inside
        ``QTableWidget.__init__``, before this class's own state exists.
        """
        shown = getattr(self, "_shown", None)
        if event.type() == QEvent.Type.PaletteChange and shown is not None:
            self.show_rows(*shown)
        super().changeEvent(event)

    def show_rows(self, progress: Progression, shown: str) -> None:
        """Every group ``shown`` names — one, or all of them — keeping the picks.

        Quiet while the rows are replaced: clearing and reselecting would announce the
        selection twice, so the host hears one change or none (``picked`` tells it which).
        """
        self._shown = (progress, shown)
        picked = self.picked()
        rows = grouped(progress)
        self.blockSignals(True)
        try:
            self.clear_rows()
            for group in GROUPS:
                steps = rows[group.key]
                if shown not in (ALL, group.key) or not steps:
                    continue
                if shown == ALL:  # One group on its own needs no heading: the filter says it.
                    self.add_heading(group.heading, key=group.key)
                for step in steps:
                    self._add(step, progress.unlocks.get(step.id, 0))
            self._reselect(picked)
        finally:
            self.blockSignals(False)

    def _add(self, step: Step, unlocks: int) -> None:
        self.add_row(
            (
                Cell(),
                Cell(
                    step.title or "Untitled step",
                    detail=self._key_of(step),
                    glyph=self._glyph(step),
                ),
                Cell(str(unlocks) if unlocks else ""),
            ),
            data={STEP_ROLE: step.id},
        )

    def _glyph(self, step: Step) -> QIcon:
        badge = self._milestone_badge(step.id)
        if badge is not None:
            return badge
        ink = QColor(self.palette().text().color())
        ink.setAlpha(SECONDARY_ALPHA)
        painter = glyph_painter(self._glyph_of(step)) or step_icon
        return painter(ink)

    # -- reading it back ------------------------------------------------------------------

    def step_at(self, row: int) -> StepId | None:
        item = self.item(row, STEP_COLUMN)
        found = item.data(STEP_ROLE) if item is not None else None
        return found if isinstance(found, str) else None

    def steps(self) -> list[StepId]:
        """Every step listed, top to bottom."""
        return [step_id for row in range(self.rowCount()) if (step_id := self.step_at(row))]

    def picked(self) -> list[StepId]:
        """The ticked steps, top to bottom."""
        rows = sorted({index.row() for index in self.selectedIndexes()})
        return [step_id for row in rows if (step_id := self.step_at(row)) is not None]

    def row_of(self, step_id: StepId) -> int | None:
        return next((row for row in range(self.rowCount()) if self.step_at(row) == step_id), None)

    def _reselect(self, step_ids: list[StepId]) -> None:
        """Keep the picks across a rebuild, by step — the rows are new."""
        wanted = set(step_ids)
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        model = self.selectionModel()
        for row in range(self.rowCount()):
            if self.step_at(row) in wanted:
                model.select(self.model().index(row, STEP_COLUMN), flags)
