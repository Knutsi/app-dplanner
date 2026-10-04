"""The order view's table: one row per step, in the order the work can be done.

A table rather than a nested list, because the thing being shown *is* a sorted sequence and
the first thing you want from one is a position. The wave rides along as a column: two steps
sharing a wave can be started together, and the first wave is the answer to "what now".

The row look — the glyph of what a step is, the milestone's badge and shade, the done mark,
the kind switches — is ``framework/step_table.py``'s :class:`StepTable`, which the
Expenditure tab (``agent_usage``) hosts too; this table follows it with the wave, the
estimate and the aspects.

**No calendar.** The table once ran the order out as dates — accumulated days, days since
the last milestone, a landing date per row — one worker after another from a start date
set on this page. That is not how the work happens and not how the plan is scheduled
(``schedule`` simulates two pools of workers), so the tab states the volume instead
and leaves dating to ``dplanner schedule show``. The estimate stays: it is the step's own
fact, rendered with ``planning/schedule.py``'s formatter so this table and the terminal
cannot express one number two ways.

Rebuilt whenever the graph changes. A project holds tens of steps, so a whole redraw is
cheaper to read than a diff and cannot go stale.
"""

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import StepId
from dplanner.domain.ordering import Placed
from dplanner.framework.step_table import LEAD, StepTable
from dplanner.framework.table import Cell, Column
from dplanner.planning.schedule import Scheduled, format_days

COLUMNS = (
    *LEAD,
    Column("Wave"),
    Column("Estimate", numeric=True),
    # What the aspect modules say about the step; the last column takes the slack.
    Column(""),
)
# Positions in ``COLUMNS``, for whoever reads a row back by column rather than by name.
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ASPECTS_COLUMN = 4


class OrderTable(StepTable):
    """The order: each step's wave, its estimate and what its aspects say."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        milestone_label: Callable[[StepId], str] = lambda _step_id: "",
        step_icons: Callable[[StepId], tuple[str, ...]] = lambda _step_id: (),
        milestone_color: Callable[[StepId], str] = lambda _step_id: "",
        step_key: Callable[[StepId], str] = lambda _step_id: "",
        step_done: Callable[[StepId], bool] = lambda _step_id: False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            COLUMNS[len(LEAD) :],
            milestone_label,
            step_icons,
            milestone_color,
            step_key,
            step_done,
            parent,
        )
        self._wave_label = wave_label
        self._step_aspects = step_aspects

    def show_order(self, order: Sequence[Scheduled]) -> None:
        days = {scheduled.place.step.id: scheduled.days for scheduled in order}

        def trailing(place: Placed, fixed: bool) -> Sequence[Cell]:
            return (
                Cell(self._wave_label(place.wave - 1), emphasis=fixed),
                Cell(format_days(days[place.step.id]), emphasis=fixed),
                Cell(
                    " · ".join(self._step_aspects(place.step.id)),
                    secondary=not fixed,
                    emphasis=fixed,
                ),
            )

        self.show_steps([scheduled.place for scheduled in order], trailing)
