"""What a feature says in a report: the spec passages it was read from.

Its name and its prose are the *step's* — the title the row already carries, the
description ``step_description`` already contributes — so the only facet left here is the
one nothing else can say: where in a specification this feature came from.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from dplanner.cli.report.parts import Contribution, Facet, ReportSource
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import read


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor) -> Contribution:
        facets = {}
        for step in project.steps:
            cites = read(step)
            if not cites:
                continue
            lines = []
            for citation in cites:
                page = f" p.{citation.page}" if citation.page is not None else ""
                quote = citation.quote.strip().replace("\n", " ")
                lines.append(
                    f"- **{citation.document}**{page}" + (f" — “{quote}”" if quote else "")
                )
            facets[step.id] = (Facet("Read from", "\n".join(lines), kind="markdown"),)
        return Contribution(facets=facets)

    return source
