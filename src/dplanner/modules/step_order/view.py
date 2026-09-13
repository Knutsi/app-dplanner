"""The order view's table: one row per step, in the order the work can be done.

A table rather than a nested list, because the thing being shown *is* a sorted sequence and
the first thing you want from one is a position. The wave rides along as a column: two steps
sharing a wave can be started together, and the first wave is the answer to "what now".

Every row wears the glyph of what it is — its key as a badge for a milestone, the layer
stack for a feature, a card for a work step — and the host can *narrow* the table to the
steps or to the features: the rows the other kind occupies are hidden, never removed, so
the numbering still reads as the whole order. A milestone is never hidden; with only the
milestones and the features showing, the table is the roadmap — what each milestone adds.

**No calendar.** The table once ran the order out as dates — accumulated days, days since
the last milestone, a landing date per row — one worker after another from a start date
set on this page. That is not how the work happens and not how the plan is scheduled
(``time_estimates`` simulates two pools of workers), so the tab states the volume instead
and leaves dating to ``dplanner schedule show``. The estimate stays: it is the step's own
fact, rendered with ``domain/schedule.py``'s formatter so this table and the terminal
cannot express one number two ways.

Rebuilt whenever the graph changes. A project holds tens of steps, so a whole redraw is
cheaper to read than a diff and cannot go stale.
"""

from collections.abc import Callable, Sequence

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

from dplanner.domain.model import StepId
from dplanner.domain.schedule import Scheduled, format_days
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Table
from dplanner.theme.icons import key_badge_icon, layers_icon, step_icon
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import recoloured

COLUMNS = (
    Column("#", numeric=True),
    Column("Step", glyph=True, resize="interactive"),
    Column("Wave"),
    Column("Estimate", numeric=True),
    # What the aspect modules say about the step; the last column takes the slack.
    Column(""),
)
# Positions in ``COLUMNS``, for whoever reads a row back by column rather than by name.
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ASPECTS_COLUMN = 4

# Stamped on every cell of a row, so a click on any column answers the same question.
# Numbered from ``HOST_ROLE``, which is where the table's own delegate stops reading.
STEP_ROLE = HOST_ROLE + 0  # The step this row is about.
MILESTONE_ROLE = HOST_ROLE + 1  # Its milestone label; falsy on an ordinary row.
COLOR_ROLE = HOST_ROLE + 2  # That milestone's shade of the project's map, "#rrggbb".

# What a row is, read off the kind vocabulary: a milestone is always shown, a feature and a
# work step each follow their own switch on the host.
KIND_MILESTONE = "milestone"
KIND_FEATURE = "feature"
KIND_STEP = "step"

# The wash under a milestone's row, low-alpha so it reads on every theme (DESIGN.md
# exception #2), and the ink its key badge wears. Both are the family every milestone wore
# before the project's colour map reached this table; a row that carries a shade
# (``COLOR_ROLE``) is these alphas over *its* hue, so the row, the card on the canvas and
# the band in the calendar are one milestone in one colour.
MILESTONE_ROW_TINT = QColor(150, 130, 220, 22)
MILESTONE_INK = QColor(150, 130, 220, 160)


def _kind(kinds: tuple[str, ...], milestone: bool) -> str:
    """Which switch a row follows. A milestone answers to none; a feature that is also a
    milestone is a milestone first, the way its icon leads with the tag."""
    if milestone or "tag" in kinds:
        return KIND_MILESTONE
    return KIND_FEATURE if "layers" in kinds else KIND_STEP


class OrderTable(Table):
    """Steps in topological order: index, name, wave and what each one costs.

    Every rule the design system has for a table comes from :class:`Table` — the header,
    the row height from the font, the hover wash, the picked row's edge, the glyph slot
    reserved on every row. What is this table's own is what a row *means*: which switch it
    follows (``_kinds``), and that a milestone is the fixed point among its neighbours,
    marked the way the primitive marks one — its key as a badge, bold, over its own shade.
    """

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        milestone_label: Callable[[StepId], str] = lambda _step_id: "",
        step_icons: Callable[[StepId], tuple[str, ...]] = lambda _step_id: (),
        milestone_color: Callable[[StepId], str] = lambda _step_id: "",
        step_key: Callable[[StepId], str] = lambda _step_id: "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(COLUMNS, parent=parent)
        self._wave_label = wave_label
        self._step_aspects = step_aspects
        self._milestone_label = milestone_label
        self._step_icons = step_icons
        self._milestone_color = milestone_color
        self._step_key = step_key
        self._kinds: list[str] = []  # One per row, in row order.
        self._shown = {KIND_STEP: True, KIND_FEATURE: True}

    def show_order(self, order: Sequence[Scheduled]) -> None:
        selected = self.selected_step()
        self.clear_rows()
        self._kinds = []
        for scheduled in order:
            place = scheduled.place
            milestone = self._milestone_label(place.step.id)
            kinds = self._step_icons(place.step.id)
            shade = self._milestone_color(place.step.id) if milestone else ""
            self._kinds.append(_kind(kinds, bool(milestone)))
            # The one weight in the table, and the whole row takes it: a milestone is where
            # a block of work lands, and a glance down the column finds them without reading.
            fixed = bool(milestone)
            cells = (
                Cell(str(place.index), secondary=not fixed, emphasis=fixed),
                Cell(
                    place.step.title or "Untitled step",
                    glyph=self._title_icon(kinds, place.step.id, shade),
                    emphasis=fixed,
                ),
                Cell(self._wave_label(place.wave - 1), emphasis=fixed),
                Cell(format_days(scheduled.days), emphasis=fixed),
                Cell(
                    " · ".join(self._step_aspects(place.step.id)),
                    secondary=not fixed,
                    emphasis=fixed,
                ),
            )
            self.add_row(
                cells,
                tint=(recoloured(MILESTONE_ROW_TINT, shade) if shade else MILESTONE_ROW_TINT)
                if fixed
                else None,
                data={
                    STEP_ROLE: place.step.id,
                    MILESTONE_ROLE: milestone,
                    COLOR_ROLE: shade,
                },
            )
        self.fit_columns()
        self._apply_filter()
        if selected is not None:
            self.select_step(selected)

    def show_kinds(self, *, steps: bool, features: bool) -> None:
        """Narrow the table to the work steps, the features, both or — with neither — the
        milestones alone. Rows hide rather than leave, so the order stays whole."""
        self._shown = {KIND_STEP: steps, KIND_FEATURE: features}
        self._apply_filter()

    def _apply_filter(self) -> None:
        for row, kind in enumerate(self._kinds):
            self.setRowHidden(row, not self._shown.get(kind, True))

    def kind_at(self, row: int) -> str:
        return self._kinds[row]

    def _title_icon(self, kinds: tuple[str, ...], step_id: StepId, shade: str) -> QIcon:
        """What the row is, in the canvas medallions' vocabulary: the **key as a badge** for
        a milestone, the layer stack for a feature, the card for a work step.

        One icon per row: a step that is several things at once leads with the rarer claim
        ("tag" sorts first), and the trailing aspects column still says the rest. A milestone
        wears its key rather than a tag glyph (DESIGN.md's *Tables*) — the key is what a
        milestone is known by across the graph — in its own shade of the project's map.
        """
        faded = QColor(self.palette().text().color())
        faded.setAlpha(SECONDARY_ALPHA)
        if "tag" in kinds:
            return key_badge_icon(self._step_key(step_id), shade or MILESTONE_INK)
        if "layers" in kinds:
            return layers_icon(faded)
        return step_icon(faded)

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
