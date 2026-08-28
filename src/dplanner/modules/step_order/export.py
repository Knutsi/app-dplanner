"""Export the order table: the same walk, written as data a spreadsheet can compute with.

The window's table and ``dplanner order show`` render through the shared formatters; a CSV
is opened to sort, sum and chart, and "2.4w" defeats all three. So this file writes the
underlying values — day counts as plain numbers, dates as ISO — which is the derived data
itself, not a second rendering of it. The columns still mirror the table one for one.

``since_release`` lives here rather than in the view because the table and the export both
show it, and two copies of the loop is how the two would one day disagree.

Qt-free by design, so the rows could feed a CLI verb without touching a window.
"""

import csv
from collections.abc import Callable, Sequence
from pathlib import Path

from dplanner.domain.model import StepId
from dplanner.domain.schedule import Scheduled
from dplanner.modules.step_order.cli import wave_label

HEADERS = (
    "#",
    "Step",
    "Wave",
    "Estimate (days)",
    "Accumulated (days)",
    "Since release (days)",
    "Date",
    "Release",
    "Aspects",
)


def since_release(
    order: Sequence[Scheduled], release_label: Callable[[StepId], str]
) -> dict[StepId, float]:
    """The working days each release closes: its accumulated total minus the previous release's.

    Keyed by the release step's id; a step that is not a release has no entry. The first
    release measures from the start of the plan, which is what "since last release" means
    when there has not been one yet.
    """
    spans: dict[StepId, float] = {}
    last = 0.0
    for scheduled in order:
        if release_label(scheduled.place.step.id):
            spans[scheduled.place.step.id] = scheduled.accumulated - last
            last = scheduled.accumulated
    return spans


def _days(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def order_rows(
    order: Sequence[Scheduled],
    step_aspects: Callable[[StepId], list[str]],
    release_label: Callable[[StepId], str],
) -> list[list[str]]:
    """The header row and one row per step, in the order the work can be done."""
    spans = since_release(order, release_label)
    rows = [list(HEADERS)]
    for scheduled in order:
        place = scheduled.place
        step_id = place.step.id
        rows.append(
            [
                str(place.index),
                place.step.title or "Untitled step",
                wave_label(place.wave - 1),
                _days(scheduled.days),
                _days(scheduled.accumulated),
                _days(spans.get(step_id)),
                scheduled.finish.isoformat() if scheduled.finish else "",
                release_label(step_id),
                "; ".join(step_aspects(step_id)),
            ]
        )
    return rows


def write_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    # utf-8-sig: the BOM is what makes Excel read the file as Unicode.
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)
