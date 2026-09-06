"""What a feature says in a report: the record a feature step realises, with its prose.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from dplanner.cli.report.parts import Contribution, Facet, ReportSource, images_in
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import MODULE_ID, read
from dplanner.modules.feature.catalogue import read_catalogue


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, files: FilesFor) -> Contribution:
        records = {record.id: record for record in read_catalogue(project)}
        facets = {}
        for step in project.steps:
            record = records.get(read(step) or "")
            if record is None:
                continue
            found = [Facet("Feature", record.title)]
            if record.description:
                found.append(
                    Facet(
                        "Feature description",
                        record.description,
                        kind="markdown",
                        images=images_in(record.description, files(project.id, MODULE_ID)),
                    )
                )
            facets[step.id] = tuple(found)
        return Contribution(facets=facets)

    return source
