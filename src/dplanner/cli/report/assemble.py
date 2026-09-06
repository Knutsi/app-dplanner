"""Every module's contribution, merged into one report.

The composition root hands :func:`build` the sources — one ``report_source()`` per module
that has something to say — and the readers every step row needs (its key, its kind, its
status), exactly as it hands lint its checks. What comes out is plain data the renderers
read and nothing else does: the window builds it on the GUI thread and renders it on a
worker; the CLI does both inline.

The one part assembled here rather than contributed is the **steps table**: the key and
the title of every step, the kind and status words, then a column per facet a module
marked ``column=True``. A module says what it knows about a step once, as a facet, and
gets the drawer entry and the column from the same statement.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from dplanner.cli.report.parts import (
    SLOTS,
    Column,
    Contribution,
    Facet,
    Part,
    Placed,
    ReportSource,
    Row,
    Slot,
    Table,
    facet_column,
)
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.store import FilesFor

STEPS_TABLE_ID = "steps"
STEPS_TABLE_ORDER = 10


@dataclass(frozen=True)
class StepCard:
    """One step as the drawer shows it: who it is, and every module's facets about it."""

    id: StepId
    key: str
    title: str
    kind: str
    status: str
    facets: tuple[Facet, ...]


@dataclass(frozen=True)
class Report:
    project_id: str
    title: str
    summary: str
    day: date  # The day the plan was read — a report's only stamp.
    sections: dict[Slot, tuple[Part, ...]]
    steps: tuple[StepCard, ...]
    plan_remote: str = ""  # The plan repository's remote URL, when it has one.

    def tables(self) -> list[Table]:
        """Every table on the page, in page order — what the sheets export."""
        return [
            part
            for slot in SLOTS
            for part in self.sections.get(slot, ())
            if isinstance(part, Table)
        ]

    def step(self, step_id: StepId) -> StepCard | None:
        return next((card for card in self.steps if card.id == step_id), None)


def build(
    library: Library,
    project: Project,
    files: FilesFor,
    sources: Sequence[ReportSource],
    *,
    key_of: Callable[[Step], str],
    kind_of: Callable[[Step], str],
    status_for: Callable[[Step], str],
    plan_remote: str = "",
    today: date | None = None,
) -> Report:
    contributions = [source(library, project, files) for source in sources]
    facets_of = _facets_by_step(contributions)
    steps = tuple(
        StepCard(
            id=step.id,
            key=key_of(step),
            title=step.title or "Untitled step",
            kind=kind_of(step),
            status=status_for(step),
            facets=facets_of.get(step.id, ()),
        )
        for step in _in_key_order(project.steps)
    )
    placed = [entry for contribution in contributions for entry in contribution.placed]
    placed.append(Placed("steps", STEPS_TABLE_ORDER, _steps_table(steps)))
    sections: dict[Slot, tuple[Part, ...]] = {}
    for slot in SLOTS:
        in_slot = sorted(
            (entry for entry in placed if entry.slot == slot), key=lambda entry: entry.order
        )
        if in_slot:
            sections[slot] = tuple(entry.part for entry in in_slot)
    return Report(
        project_id=project.id,
        title=project.title or "Untitled project",
        summary=project.summary,
        day=today or date.today(),
        sections=sections,
        steps=steps,
        plan_remote=plan_remote,
    )


def _facets_by_step(contributions: Sequence[Contribution]) -> dict[StepId, tuple[Facet, ...]]:
    merged: dict[StepId, list[Facet]] = {}
    for contribution in contributions:
        for step_id, facets in contribution.facets.items():
            merged.setdefault(step_id, []).extend(facets)
    return {step_id: tuple(facets) for step_id, facets in merged.items()}


def _in_key_order(steps: Sequence[Step]) -> list[Step]:
    """By number, the way a key reads; an unnumbered step (a legacy import) sorts last."""
    return sorted(steps, key=lambda step: (step.number == 0, step.number, step.title))


def _steps_table(steps: Sequence[StepCard]) -> Table:
    columns: list[Column] = [
        Column("Key", "key"),
        Column("Step"),
        Column("Kind"),
        Column("Status", "status"),
    ]
    facet_labels: list[str] = []
    for card in steps:
        for facet in card.facets:
            if facet.column and facet.label not in facet_labels:
                facet_labels.append(facet.label)
                columns.append(facet_column(facet))
    rows = tuple(
        Row(
            cells=(
                card.key,
                card.title,
                card.kind,
                card.status,
                *(_facet_value(card, label) for label in facet_labels),
            ),
            step_id=card.id,
            strong=card.kind == "milestone",
        )
        for card in steps
    )
    return Table(STEPS_TABLE_ID, "Steps", tuple(columns), rows)


def _facet_value(card: StepCard, label: str) -> str:
    return next((facet.value for facet in card.facets if facet.label == label), "")
