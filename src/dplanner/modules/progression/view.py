"""The Step statuses table: what needs a person right now, grouped, a box on every row —
one project's, or every project's in the Control Centre.

Pure rendering — the domain's :class:`~dplanner.domain.progression.Progression` arrives
computed and the table is rebuilt wholesale, so nothing here can disagree with the model.
The groups are the partitions a person acts on, in the order they are closest to done —
Blocked, Ready to merge, Ready for review, Ready to start — and then Waiting, what cannot
start yet. Work in progress is not listed: an agent at work needs nobody, and the tab is
for the rows that do.

**The box is the selection.** The first column is a check column (``Column(check=True)``):
ticking a row picks it, and the host publishes what is picked, so the strip's verbs, the
right-click Step menu and Run Agent's profiles all act on exactly the ticked rows. The
picks survive a rebuild by step id — an accepted review is still ticked in its new group.

A row's glyph is Find's: a milestone's key as a badge in its own shade, otherwise who works
the step — the glyph its key block wears — painted in the palette's ink, so a palette change
paints the rows again (``changeEvent``): a colour taken out of the palette goes stale.

**A row names its project only where the rows span several** — the Project column stands
down on one project's tab, where every row would say the same. **And a row ends in its ⋮**
(``Column(menu=True)``): the host builds that row's verbs when it is pressed.
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
CHECK_COLUMN, STEP_COLUMN, PROJECT_COLUMN, UNBLOCKS_COLUMN, MENU_COLUMN = range(5)
COLUMNS = (
    Column("", check=True),
    Column("Step", glyph=True, detail=True, resize="stretch"),
    Column("Project"),
    Column("Unblocks", numeric=True),
    Column("", menu=True),
)
ROW_MENU_TIP = "What you can do with this step"

ALL = "all"


@dataclass(frozen=True)
class Group:
    """One kind of row: its key (the filter's value and the heading's fold), the heading's
    words, the filter's word, what the table says when it is the only one and empty, its
    steps in the order the derivation ranked them, and whether they wait on a person —
    everything but Waiting does, which is the rest of the plan."""

    key: str
    heading: str
    label: str
    empty: str
    rows: Callable[[Progression], tuple[Step, ...]]
    needs_person: bool = True


GROUPS = (
    Group("blocked", "Blocked", "Blocked", "Nothing is blocked.", lambda found: found.attention),
    Group(
        "merge",
        "Ready to merge",
        "Merge",
        "Nothing is waiting on a merge.",
        lambda found: found.merge,
    ),
    Group(
        "review",
        "Ready for review",
        "Review",
        "Nothing is ready for review.",
        lambda found: found.review,
    ),
    Group(
        "start", "Ready to start", "Start", "Nothing is ready to start.", lambda found: found.ready
    ),
    Group(
        "waiting",
        "Waiting",
        "Waiting",
        "Nothing is waiting.",
        lambda found: (*(coming.step for coming in found.upcoming), *found.waiting),
        needs_person=False,
    ),
)


def needing_a_person(progress: Progression) -> int:
    return sum(len(group.rows(progress)) for group in GROUPS if group.needs_person)


class StatusTable(Table):
    """The rows, grouped; ``show_rows`` rebuilds them for one filter."""

    def __init__(
        self,
        *,
        key_of: Callable[[Step], str],
        glyph_of: Callable[[Step], str],
        milestone_badge: Callable[[StepId], QIcon | None],
        project_of: Callable[[Step], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(COLUMNS, selection="extended", parent=parent)
        self._key_of = key_of
        self._glyph_of = glyph_of
        self._milestone_badge = milestone_badge
        self._project_of = project_of
        self._shown: tuple[Progression, str, bool] | None = None
        self.setColumnHidden(PROJECT_COLUMN, True)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """The glyphs again, in the new theme's ink.

        ``getattr``, not a plain read: Qt delivers a PaletteChange from inside
        ``QTableWidget.__init__``, before this class's own state exists.
        """
        shown = getattr(self, "_shown", None)
        if event.type() == QEvent.Type.PaletteChange and shown is not None:
            progress, group, spans = shown
            self.show_rows(progress, group, spans=spans)
        super().changeEvent(event)

    def show_rows(self, progress: Progression, shown: str, *, spans: bool = False) -> None:
        """Every group ``shown`` names — one, or all of them — keeping the picks; ``spans``
        when the rows come from several projects, which is when each names its own.

        Quiet while the rows are replaced: clearing and reselecting would announce the
        selection twice, so the host hears one change or none (``picked`` tells it which).
        """
        self._shown = (progress, shown, spans)
        self.setColumnHidden(PROJECT_COLUMN, not spans)
        picked = self.picked()
        self.blockSignals(True)
        try:
            self.clear_rows()
            for group in GROUPS:
                steps = group.rows(progress)
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
                Cell(self._project_of(step)),
                Cell(str(unlocks) if unlocks else ""),
                Cell(tooltip=ROW_MENU_TIP),
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
