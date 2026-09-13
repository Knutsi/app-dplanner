"""What a collector compiles from, and whether what it compiled is still true.

One function with four readers — the Documentation tab, ``dplanner docs collect``,
``docs status`` and the compile briefing (:mod:`dplanner.modules.docs.prompt`) — for the same
reason ``notes/reach.py`` is one: an accumulation each surface computed for itself would
be four answers to one question. Nothing is stored;
``dplanner step link`` relinks a graph with no window running to notice a stored list going
stale.

**A collector reads its sub-collectors' compiled documents, not their raw notes.** A feature
gathers nothing finer (``ScopeKind.gathers`` is empty for it), so it reads fragments flat. A
milestone gathers features, so it folds each feature's *compiled* document — falling back to
that feature's fragments where it has none — plus the fragments of everything in its cone no
feature took. Two things follow, and they are the reason for the shape: a milestone reads
polished prose rather than the same notes twice, and **recompiling a feature makes its
milestone stale by itself**, because the milestone's sources changed.

**Staleness is a digest, not a timestamp.** Nothing records when a fragment was last edited,
and adding that to support one check would be storing a derivation. Instead a compile stores
the digest of what it read, and "is this out of date" is a comparison — exact, and correct
across a relink that changes what a collector gathers.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import (
    ScopeKind,
    StepPredicate,
    cone,
    kind_of,
    leaders,
    stops_for,
)
from dplanner.modules.docs.aspect import read, read_compiled, read_digest

# What a heading over one contribution says. A title is the only thing a reader has to tell
# two contributions apart, so an untitled step still gets one.
UNTITLED = "Untitled step"

# Never compiled / compiled and still true / compiled from something that has since changed.
type CompiledState = Literal["never", "current", "stale"]


@dataclass(frozen=True)
class Source:
    """One block a compile reads: which step it came from, and whether it is already prose.

    ``compiled`` is what separates a feature's polished document from a step's raw note, and
    it is what the heading and the prompt both want to know.
    """

    step: Step
    body: str
    compiled: bool = False


def fragments(
    library: Library,
    project: Project,
    step_id: StepId,
    *,
    stops_at: StepPredicate | None = None,
) -> list[Source]:
    """Every documented step at and behind ``step_id`` — the raw notes, nothing folded.

    The origin is added back: ``cone`` excludes it, and a collector's own note is part of
    what it holds, the same way ``testing.aspect.covered`` counts a step's own tests.
    """
    found = cone(library, project, step_id, stops_at=stops_at)
    reach = {step.id for step in found.steps} | {step_id}
    return [Source(step, read(step)) for step in project.steps if step.id in reach and read(step)]


def sources_for(
    kinds: Sequence[ScopeKind], library: Library, project: Project, step_id: StepId
) -> list[Source]:
    """What compiling ``step_id`` would read, in project order.

    A step that collects nothing reads its whole upstream cone, which is what a plain step
    would mean if anybody asked.
    """
    origin = project.step(step_id)
    if origin is None:
        return []
    stops = stops_for(kinds, origin)
    kind = kind_of(kinds, origin)
    walked = cone(library, project, step_id, stops_at=stops)
    sub = leaders(kinds, kind, walked.steps) if kind is not None else []

    # Each sub-collector speaks for its own cone, so nothing it holds is read twice.
    taken: set[StepId] = set()
    for leader in sub:
        held = cone(library, project, leader.id, stops_at=stops_for(kinds, leader))
        taken |= {step.id for step in held.steps} | {leader.id}

    folded = {leader.id: leader for leader in sub}
    found: list[Source] = []
    for step in [*walked.steps, *([origin] if origin is not None else [])]:
        if step.id in folded:
            document = read_compiled(step)
            # No document yet: fall back to its own notes rather than dropping the feature,
            # so a half-compiled project still produces something honest.
            if document:
                found.append(Source(step, document, compiled=True))
            else:
                found += fragments(library, project, step.id, stops_at=stops_for(kinds, step))
        elif step.id not in taken and read(step):
            found.append(Source(step, read(step)))
    order = {step.id: index for index, step in enumerate(project.steps)}
    return sorted(found, key=lambda source: order.get(source.step.id, len(order)))


def sub_collectors(
    kinds: Sequence[ScopeKind], library: Library, project: Project, step_id: StepId
) -> list[Step]:
    """The collectors ``step_id`` folds the documents of — the features inside a milestone.

    The same two calls :func:`sources_for` makes, named on their own because *whose document
    must be compiled first* is a question the window asks when it compiles a whole project:
    a milestone compiled beside its features would read documents about to change.
    """
    origin = project.step(step_id)
    if origin is None:
        return []
    kind = kind_of(kinds, origin)
    if kind is None:
        return []
    walked = cone(library, project, step_id, stops_at=stops_for(kinds, origin))
    return list(leaders(kinds, kind, walked.steps))


def as_markdown(sources: Sequence[Source], level: int = 2) -> str:
    """The sources as one document, each under its step's title.

    Level two by default, because a contribution may open with its own ``#`` and two h1s in a
    document is a document with no shape. A caller that nests them under a heading of its own
    — the compile briefing, whose blocks are the ``##`` — asks for one level deeper.
    """
    heading = "#" * level
    return "\n\n".join(
        f"{heading} {source.step.title or UNTITLED}\n\n{source.body.strip()}" for source in sources
    )


def digest(sources: Sequence[Source]) -> str:
    """A stable fingerprint of what a compile read.

    Sixteen hex characters of sha256 over the assembled markdown — the same convention
    ``domain/assets.py`` content-addresses blobs with, and short enough to read in a diff.
    """
    return hashlib.sha256(as_markdown(sources).encode("utf-8")).hexdigest()[:16]


def state_of(
    kinds: Sequence[ScopeKind], library: Library, project: Project, step_id: StepId
) -> CompiledState:
    """Whether ``step_id``'s compiled document is missing, current, or out of date."""
    step = project.step(step_id)
    if step is None:
        return "never"
    return compiled_state(step, sources_for(kinds, library, project, step_id))


def compiled_state(step: Step, found: Sequence[Source]) -> CompiledState:
    """:func:`state_of` for a caller that already holds what the step would read.

    The walk is the expensive half of the question, so a reader that needs both the sources
    and the state — ``docs status``, the frontier — asks once and compares here.
    """
    if not read_compiled(step):
        return "never"
    stored = read_digest(step)
    return "current" if stored and stored == digest(found) else "stale"


def frontier(
    kinds: Sequence[ScopeKind], library: Library, project: Project
) -> tuple[list[StepId], list[StepId]]:
    """Which of this project's documents want compiling now, and which must wait.

    **A collector whose own sub-collectors are out of date waits**, because a milestone
    reads its features' *compiled* documents: launching both at once would have the
    milestone read a document that is about to change, and ``docs status``'s advice says
    as much to an agent. So one gesture takes the frontier and the next takes what it
    unblocked. Both lists are in project order.

    One walk per collector. This is the whole project asked at once, and it is what the
    window's *Compile Out of Date* label shows — read from a settled answer, never computed
    inside the action's state: at four hundred steps this is a fifth of a second.
    """
    due: set[StepId] = set()
    for step in collectors(kinds, project):
        found = sources_for(kinds, library, project, step.id)
        if found and compiled_state(step, found) != "current":
            due.add(step.id)
    ready: list[StepId] = []
    waiting: list[StepId] = []
    for step in project.steps:
        if step.id not in due:
            continue
        behind = {sub.id for sub in sub_collectors(kinds, library, project, step.id)}
        (waiting if behind & due else ready).append(step.id)
    return ready, waiting


def collectors(kinds: Sequence[ScopeKind], project: Project) -> list[Step]:
    """Every step in the project that collects something, in project order."""
    return [step for step in project.steps if kind_of(kinds, step) is not None]


def word_count(body: str) -> int:
    return len(body.split())
