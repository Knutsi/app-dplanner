"""What the description says in a report: the step's prose, pictures carried along.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from datetime import date

from dplanner.cli.report.parts import Contribution, Facet, ReportSource, images_in
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.step_description.aspect import MODULE_ID, read


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, files: FilesFor, _day: date) -> Contribution:
        return Contribution(
            facets={
                step.id: (
                    Facet(
                        "Description",
                        text,
                        kind="markdown",
                        images=images_in(text, files(step.id, MODULE_ID)),
                    ),
                )
                for step in project.steps
                if (text := read(step).strip())
            }
        )

    return source
