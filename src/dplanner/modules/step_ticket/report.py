"""What a ticket says in a report: the tracker's key, linked when it has an address.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from datetime import date

from dplanner.cli.report.parts import Contribution, Facet, FacetKind, ReportSource
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.step_ticket.aspect import read


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor, _day: date) -> Contribution:
        facets = {}
        for step in project.steps:
            ticket = read(step)
            if ticket is None:
                continue
            words = " ".join(part for part in (ticket.system, ticket.key) if part) or ticket.url
            if not words:
                continue
            kind: FacetKind = "link" if ticket.url else "text"
            facets[step.id] = (Facet("Ticket", words, kind=kind, url=ticket.url),)
        return Contribution(facets=facets)

    return source
