"""What the canvas says in a report: the graph as the window would draw it.

Positions are the stored ones with the ambient layout filling the gaps
(``placement.positions``), sizes the stored ones or the default footprint; edges are the
steps' ``requires`` and ``relates`` with an end that no longer resolves skipped, as the
scene skips them. A stack is drawn as its frame behind a column of its members, and the
arrows of its chain are left out — the column says the order. What a card *wears* — its key
and the glyph over it, kind, status, the figure at its bottom right and a milestone's badge
— arrives as readers from the composition root, the same answers the canvas's
``NodeAccent`` is built from, so the page and the window cannot dress a step differently.
The glyph travels as its drawing, read from the vendored file by ``theme/glyph_source.py``:
the report's renderer lives in ``cli/``, which may not read ``theme/`` itself.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from datetime import date
from itertools import pairwise

from dplanner.cli.report.parts import (
    Contribution,
    Edge,
    EdgeKind,
    Frame,
    Graph,
    Node,
    Placed,
    ReportSource,
)
from dplanner.domain.model import EDGE_KINDS, Library, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.canvas.layouts.placement import positions
from dplanner.modules.canvas.layouts.positions import node_size
from dplanner.modules.canvas.stacks.stack import frame, read_stacks
from dplanner.planning.status import Status, Unknown
from dplanner.theme.glyph_source import glyph_markup


def report_source(
    *,
    key_of: Callable[[Step], str],
    kind_of: Callable[[Step], str],
    status_for: Callable[[Step], Status | Unknown],
    stats_of: Callable[[Library, Project], dict[StepId, str]],
    badge_of: Callable[[Step], str],
    # Every milestone's own shade, by step id — one deal per project, the same one the
    # canvas paints and the timeline bands.
    colors_of: Callable[[Library, Project], dict[StepId, str]],
    # Who works a step: the key block's glyph and its tone, as the canvas reads them.
    glyph_of: Callable[[Step], tuple[str, str]],
) -> ReportSource:
    def source(library: Library, project: Project, _files: FilesFor, _day: date) -> Contribution:
        if not project.steps:
            return Contribution()
        placed_at = positions(library, project)
        stats = stats_of(library, project)
        colors = colors_of(library, project)
        nodes = []
        for step in project.steps:
            x, y = placed_at[step.id]
            w, h = node_size(step)
            glyph, glyph_tone = glyph_of(step)
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
                    color=colors.get(step.id, ""),
                    glyph_markup=glyph_markup(glyph) if glyph else "",
                    glyph_tone=glyph_tone,
                )
            )
        stacks = read_stacks(project.steps)
        sizes = {step.id: node_size(step) for step in project.steps}
        frames = tuple(
            Frame(*frame(stack, placed_at[stack.head], sizes.__getitem__)) for stack in stacks
        )
        chained = {(one, two) for stack in stacks for one, two in pairwise(stack.members)}
        edges = [
            Edge(source_id, step.id, kind)
            for step in project.steps
            for kind in _edge_kinds()
            for source_id in step.edges.get(kind, ())
            if project.step(source_id) is not None
            and not (kind == "requires" and (source_id, step.id) in chained)
        ]
        graph = Graph(tuple(nodes), tuple(edges), frames)
        return Contribution(placed=(Placed("plan", 10, graph),))

    return source


def _edge_kinds() -> tuple[EdgeKind, ...]:
    # The model's table names the kinds; the report draws exactly those two and no other.
    return tuple(kind for kind in ("requires", "relates") if kind in EDGE_KINDS)
