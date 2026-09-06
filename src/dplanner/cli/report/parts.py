"""What a module says in a report: a small vocabulary of plain parts, keyed by step.

A report is every feature's data on one page for a reader who has no DPlanner — and no
module may import another, so no module can draw the whole page. The split that keeps
that true: **modules say, one renderer shows.** Each participating module exports a
Qt-free ``report_source()`` from a ``report.py`` beside its ``cli.py``, returning a
:class:`Contribution` built from the parts here; the composition root hands the sources
over, as it does for assets and lint; ``assemble.py`` merges them into one report;
``page.py`` draws that as HTML and the window's ``paper.py`` as PDF, knowing only these
shapes.

**Every part is plain data** — strings, numbers, dates, bytes — never a ``Step`` or a
``Project``. That is what lets a page render on a worker thread after the model was read
on the GUI thread, and what makes the output deterministic: the same plan gives the same
bytes. ``tests/cli/test_report.py`` walks every contribution to hold the line.

**Drill-down is a shared key.** A row, a node, a chart mark or a facet that is about a
step carries the step's id; the page keeps one selection and every view answers it. The
graph never learns about estimates, and the estimates never learn about the graph.
"""

import mimetypes
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal

from dplanner.domain.assets import image_references
from dplanner.domain.model import Library, Project, StepId
from dplanner.domain.store import FilesFor, ModuleFileArea

# Where on the page a part goes, in page order. A module places a part into a slot and
# ranks it there with ``order`` (10/20/30…), the way an action names a menu and a group.
Slot = Literal["overview", "plan", "timeline", "order", "steps", "decisions"]
SLOTS: Final[tuple[Slot, ...]] = ("overview", "plan", "timeline", "order", "steps", "decisions")
SLOT_TITLES: Final[dict[Slot, str]] = {
    "overview": "Overview",
    "plan": "Plan",
    "timeline": "Timeline",
    "order": "Order",
    "steps": "Steps",
    "decisions": "Decisions",
}

# The window's tones, by name: busy blue, bad red, good green, and quiet ("").
Tone = Literal["", "good", "busy", "bad"]
ColumnKind = Literal["text", "number", "days", "date", "status", "key"]
FacetKind = Literal["text", "markdown", "link", "status", "days", "date"]
EdgeKind = Literal["requires", "relates"]
SeriesRole = Literal["plan", "baseline", "actual"]


@dataclass(frozen=True)
class Image:
    """One picture a markdown part refers to, carried as bytes so the page can inline it."""

    name: str  # As referenced in the markdown: ``assets/<sha16>.png``.
    data: bytes
    mime: str


@dataclass(frozen=True)
class Figure:
    """A headline: one number or date with its label — "Lands", "14 Feb '27"."""

    label: str
    value: str
    note: str = ""
    tone: Tone = ""


@dataclass(frozen=True)
class Column:
    label: str
    kind: ColumnKind = "text"


@dataclass(frozen=True)
class Row:
    cells: tuple[str, ...]
    step_id: StepId = ""
    strong: bool = False  # A fixed point among its neighbours: the order table's milestones.


@dataclass(frozen=True)
class Table:
    id: str
    title: str
    columns: tuple[Column, ...]
    rows: tuple[Row, ...]
    note: str = ""


@dataclass(frozen=True)
class Series:
    label: str
    points: tuple[tuple[date, float], ...]
    role: SeriesRole


@dataclass(frozen=True)
class Mark:
    """A named hairline on a chart: where the plan lands a milestone."""

    day: date
    label: str
    step_id: StepId = ""


@dataclass(frozen=True)
class Chart:
    """Shares over dates — the progress chart. ``idle`` names the spans the plan leaves
    empty, drawn flat and dotted."""

    id: str
    title: str
    today: date
    series: tuple[Series, ...]
    marks: tuple[Mark, ...] = ()
    idle: tuple[tuple[date, date], ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Span:
    """One bar on a timeline: a milestone's stretch, from its start to where it lands."""

    label: str
    start: date
    finish: date | None
    color: str  # "#rrggbb"
    step_id: StepId = ""
    asked: date | None = None  # The date somebody set for it, when they did.
    share: float | None = None  # How much of it has landed, 0..1.


@dataclass(frozen=True)
class Timeline:
    id: str
    title: str
    today: date
    spans: tuple[Span, ...]


@dataclass(frozen=True)
class Prose:
    """A markdown document with a title: a decision, a compiled note."""

    id: str
    title: str
    markdown: str
    meta: str = ""
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class Node:
    """A card on the graph, as the canvas would place and dress it."""

    id: StepId
    key: str
    title: str
    x: float
    y: float
    w: float
    h: float
    kind: str = ""  # milestone | feature | check | agent | ""
    status: str = ""  # pending | in-progress | done | blocked
    stat: str = ""  # The card's bottom-right figure: an estimate, a milestone's total.
    badge: str = ""  # A milestone's label on the top edge.


@dataclass(frozen=True)
class Edge:
    source: StepId
    target: StepId  # The step that waits.
    kind: EdgeKind


@dataclass(frozen=True)
class Region:
    title: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    regions: tuple[Region, ...] = ()


Part = Figure | Table | Chart | Timeline | Prose | Graph


@dataclass(frozen=True)
class Facet:
    """One fact a module states about one step, for the step's drawer — and, with
    ``column``, for a column of the steps table."""

    label: str
    value: str
    kind: FacetKind = "text"
    url: str = ""
    column: bool = False
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class Placed:
    slot: Slot
    order: int
    part: Part


@dataclass(frozen=True)
class Contribution:
    """What one module says about a project: parts placed on the page, and facets per step."""

    placed: tuple[Placed, ...] = ()
    facets: Mapping[StepId, tuple[Facet, ...]] = field(default_factory=dict)


ReportSource = Callable[[Library, Project, FilesFor], Contribution]

NOTHING: Final = Contribution()


def images_in(markdown: str, area: ModuleFileArea) -> tuple[Image, ...]:
    """The pictures ``markdown`` refers to that ``area`` holds, as bytes.

    Only the module that owns a prose knows which file area its links point into, so it
    calls this while it still has the area; the page then needs no filesystem at all.
    """
    found: list[Image] = []
    for name in image_references(markdown):
        data = area.read_bytes(name)
        if data is None:
            continue
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        found.append(Image(name, data, mime))
    return tuple(found)


def facet_column(facet: Facet) -> Column:
    """The steps-table column a ``column=True`` facet earns."""
    kinds: dict[FacetKind, ColumnKind] = {"days": "days", "date": "date", "status": "status"}
    return Column(facet.label, kinds.get(facet.kind, "text"))
