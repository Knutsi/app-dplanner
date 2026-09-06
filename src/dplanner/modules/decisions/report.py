"""What the decision log says in a report: every standing decision, as prose.

A superseded decision is history, not guidance, so it stays out — the same cut the
briefing's *Decisions so far* makes.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from datetime import date

from dplanner.cli.report.parts import Contribution, Placed, Prose, ReportSource
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import format_date
from dplanner.domain.store import FilesFor
from dplanner.modules.decisions.log import Decision, read_log, standing


def report_source(*, key_of: Callable[[Step], str]) -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor) -> Contribution:
        placed = tuple(
            Placed("decisions", 10 + index, _prose(project, record, key_of))
            for index, record in enumerate(standing(read_log(project)))
        )
        return Contribution(placed=placed)

    return source


def _prose(project: Project, record: Decision, key_of: Callable[[Step], str]) -> Prose:
    meta = []
    if record.made:
        try:
            meta.append(format_date(date.fromisoformat(record.made)))
        except ValueError:
            meta.append(record.made)
    step = project.step(record.step) if record.step else None
    if step is not None:
        meta.append(f"on {key_of(step) or step.title}")
    if record.supersedes:
        meta.append(f"supersedes {record.supersedes}")
    return Prose(record.id, f"{record.id} · {record.title}", record.body, meta=" · ".join(meta))
