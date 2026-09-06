"""What a handoff says in a report: the note a step passes forward.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from dplanner.cli.report.parts import Contribution, Facet, ReportSource, images_in
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.step_handoff.aspect import MODULE_ID, read_note


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, files: FilesFor) -> Contribution:
        return Contribution(
            facets={
                step.id: (
                    Facet(
                        "Handoff",
                        note,
                        kind="markdown",
                        images=images_in(note, files(step.id, MODULE_ID)),
                    ),
                )
                for step in project.steps
                if (note := read_note(step).strip())
            }
        )

    return source
