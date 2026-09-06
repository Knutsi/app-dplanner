"""What the canvas says in a report: the graph as the window would draw it.

Positions are the stored ones with the ambient layout filling the gaps
(``placement.positions``), sizes the stored ones or the default footprint, regions the
project's own; edges are the steps' ``requires`` and ``relates`` with an end that no longer
resolves skipped, as the scene skips them. What a card *wears* — its key, kind, status, the
figure at its bottom right and a milestone's badge — arrives as readers from the composition
root, the same answers the canvas's ``NodeAccent`` is built from, so the page and the
window cannot dress a step differently.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable

from dplanner.cli.report.parts import (
    Contribution,
    Edge,
    EdgeKind,
    Graph,
    Node,
    Placed,
    Region,
    ReportSource,
)
from dplanner.domain.model import EDGE_KINDS, Library, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import node_size
from dplanner.modules.project_editor.regions import read_regions


def report_source(
    *,
    key_of: Callable[[Step], str],
    kind_of: Callable[[Step], str],
    status_for: Callable[[Step], str],
    stats_of: Callable[[Library, Project], dict[StepId, str]],
    badge_of: Callable[[Step], str],
) -> ReportSource:
    def source(library: Library, project: Project, _files: FilesFor) -> Contribution:
        if not project.steps:
            return Contribution()
        placed_at = positions(library, project)
        stats = stats_of(library, project)
        nodes = []
        for step in project.steps:
            x, y = placed_at[step.id]
            w, h = node_size(step)
            nodes.append(
                Node(
                    id=step.id,
                    key=key_of(step),
                    title=step.title or "Untitled step",
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    kind=kind_of(step),
                    status=status_for(step),
                    stat=stats.get(step.id, ""),
                    badge=badge_of(step),
                )
            )
        edges = [
            Edge(source_id, step.id, kind)
            for step in project.steps
            for kind in _edge_kinds()
            for source_id in step.edges.get(kind, ())
            if project.step(source_id) is not None
        ]
        regions = tuple(
            Region(region.title, region.x, region.y, region.w, region.h)
            for region in read_regions(project)
        )
        graph = Graph(tuple(nodes), tuple(edges), regions)
        return Contribution(placed=(Placed("plan", 10, graph),))

    return source


def _edge_kinds() -> tuple[EdgeKind, ...]:
    # The model's table names the kinds; the report draws exactly those two and no other.
    return tuple(kind for kind in ("requires", "relates") if kind in EDGE_KINDS)
