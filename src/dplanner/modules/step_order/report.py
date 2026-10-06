"""What the order says in a report: the order table, with the schedule's days and dates.

The same rows the CSV export writes (``export.order_entries``), over the planning tier's
schedule from the project's start, so the page, the window's table and the CSV are one
derivation.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from datetime import date

from dplanner.cli.report.parts import (
    Column,
    ColumnKind,
    Contribution,
    Placed,
    ReportSource,
    Row,
    Table,
)
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import placed
from dplanner.domain.store import FilesFor
from dplanner.modules.step_order.export import HEADERS, order_entries
from dplanner.planning.estimate import start_of
from dplanner.planning.schedule import schedule

TABLE_ID = "order"

_KINDS: tuple[ColumnKind, ...] = (
    "number",
    "text",
    "text",
    "days",
    "days",
    "days",
    "date",
    "text",
    "text",
)


def report_source(
    *,
    step_aspects: Callable[[Step], list[str]],
    milestone_label: Callable[[Step], str],
) -> ReportSource:
    def source(library: Library, project: Project, _files: FilesFor, _day: date) -> Contribution:
        def aspects(step_id: StepId) -> list[str]:
            step = project.step(step_id)
            return step_aspects(step) if step is not None else []

        def label(step_id: StepId) -> str:
            step = project.step(step_id)
            return milestone_label(step) if step is not None else ""

        scheduled = schedule(placed(library, project), start_of(project))
        entries = order_entries(scheduled, aspects, label)
        if not entries:
            return Contribution()
        rows = tuple(
            Row(tuple(cells), step_id=step_id, strong=bool(label(step_id)))
            for step_id, cells in entries
        )
        columns = tuple(Column(label, kind) for label, kind in zip(HEADERS, _KINDS, strict=True))
        table = Table(
            TABLE_ID,
            "Order",
            columns,
            rows,
            note="Waves are the steps that can run side by side; days accumulate along "
            "the longest chain.",
        )
        return Contribution(placed=(Placed("order", 10, table),))

    return source
