"""What a milestone says in a report: its label, on the step that marks it.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from dplanner.cli.report.parts import Contribution, Facet, ReportSource
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.step_milestone.aspect import read


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor) -> Contribution:
        return Contribution(
            facets={
                step.id: (Facet("Milestone", label),)
                for step in project.steps
                if (label := read(step))
            }
        )

    return source
