"""What progression says in a report: how far along, and what can start now.

The same derivation as the Step statuses tab and ``dplanner progression show`` — statuses and
estimates through the readers the root hands over — placed at the top of the overview,
because "how far along" is the first thing every reader asks.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from datetime import date

from dplanner.cli.report.parts import (
    Column,
    Contribution,
    Figure,
    Placed,
    ReportSource,
    Row,
    Table,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.planning.progression import progression
from dplanner.planning.status import Status

READY_TABLE_ID = "ready"


def report_source(
    *,
    status_in: Callable[[Library, date], Callable[[Step], Status]],
    counts_as_work: Callable[[Step], bool],
    days_for: Callable[[Step], float | None],
    key_of: Callable[[Step], str],
    auto_progresses: Callable[[Step, Step], bool],
) -> ReportSource:
    def source(library: Library, project: Project, _files: FilesFor, day: date) -> Contribution:
        found = progression(
            library, project, status_in(library, day), counts_as_work, auto_progresses
        )
        if not found.total:
            return Contribution()
        placed = [
            Placed(
                "overview",
                10,
                Figure(
                    "Done",
                    f"{found.percent:.0f}%",
                    note=f"{len(found.done)} of {found.total} steps",
                    tone="good" if found.done else "",
                ),
            ),
            Placed(
                "overview",
                16,
                Figure(
                    "Ready to start",
                    str(len(found.ready)),
                    note=f"{len(found.running)} running",
                    tone="busy" if found.running else "",
                ),
            ),
            Placed(
                "overview",
                18,
                Figure(
                    "Blocked",
                    str(len(found.attention)),
                    note="stuck on a person",
                    tone="bad" if found.attention else "",
                ),
            ),
        ]
        if found.ready:
            rows = tuple(
                Row(
                    (key_of(step), step.title or "Untitled step", str(found.unlocks[step.id])),
                    step_id=step.id,
                )
                for step in found.ready
            )
            placed.append(
                Placed(
                    "overview",
                    40,
                    Table(
                        READY_TABLE_ID,
                        "Ready to start",
                        (Column("Key", "key"), Column("Step"), Column("Unlocks", "number")),
                        rows,
                        note="Nothing these wait on is left undone; first the ones that "
                        "unblock the most.",
                    ),
                )
            )
        return Contribution(placed=tuple(placed))

    return source
