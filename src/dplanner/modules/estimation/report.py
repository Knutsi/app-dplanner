"""What the estimate says in a report: one facet per estimated step, and a column.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from dplanner.cli.report.parts import Contribution, Facet, ReportSource
from dplanner.domain.model import Library, Project
from dplanner.domain.schedule import format_days
from dplanner.domain.store import FilesFor
from dplanner.modules.estimation.aspect import read

LABEL = "Estimate"


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor) -> Contribution:
        facets = {}
        for step in project.steps:
            days = read(step)
            if days is not None:
                facets[step.id] = (Facet(LABEL, format_days(days), kind="days", column=True),)
        return Contribution(facets=facets)

    return source
