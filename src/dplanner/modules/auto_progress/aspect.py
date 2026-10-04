"""The auto-progress aspect: which of a step's ``requires`` links free it from review on.

A plain link is fulfilled when its source is done. A step that exists to take parallel work
and land it — three agents' branches merged by a fourth — cannot wait for that, because its
sources are done only once it has landed them. So the step that waits may name some of the
steps it requires, ``{"from": [source ids]}``, and each of those links is fulfilled as soon as
its source reads ready for review or ready to merge (``planning/progression.py``'s
``outstanding``). The step then takes each source's work, lands it and sets the source done.

**A listed id counts only while the link exists.** The flag is read *through* the edge —
:func:`flagged` intersects the list with the step's own ``requires`` — and nothing repairs it
when a link goes: removing, redirecting or isolating a link leaves the id inert, and undoing
the removal brings the flag back with the link. ``ARCHITECTURE.md``'s *An auto-progress link
is an aspect on the step that waits* weighs this against storing data on the edge.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Library, Project, Step, StepId

MODULE_ID = "auto_progress"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
FROM_KEY = "from"


def read(step: Step) -> tuple[StepId, ...]:
    """The ids the entry lists, live or not — what :func:`write` round-trips."""
    listed = (step.module_data.get(MODULE_ID) or {}).get(FROM_KEY)
    if not isinstance(listed, list):
        return ()
    return tuple(dict.fromkeys(item for item in listed if isinstance(item, str)))


def write(ids: Iterable[StepId]) -> dict[str, Any]:
    """The entry to store — ``{}`` for none, which removes the file."""
    listed = list(dict.fromkeys(ids))
    return stamped({FROM_KEY: listed}, DATA_FORMAT.version) if listed else {}


def flagged(step: Step) -> frozenset[StepId]:
    """The sources whose link into ``step`` auto-progresses: listed, and still required."""
    return frozenset(read(step)) & frozenset(step.edges.get("requires", ()))


def progresses(waiter: Step, source: Step) -> bool:
    """Whether ``waiter`` may start once ``source`` reads ready for review — asked of every
    link on every canvas sync, so it builds no sets."""
    return source.id in read(waiter) and source.id in waiter.edges.get("requires", ())


def with_sources(step: Step, sources: Iterable[StepId], on: bool) -> dict[str, Any]:
    """The step's entry with these links turned on or off, the rest as they were listed."""
    named = list(dict.fromkeys(sources))
    kept = [listed for listed in read(step) if listed not in named]
    return write([*kept, *named] if on else kept)


def sources(library: Library, waiter: Step) -> list[Step]:
    """The steps ``waiter`` collects — its auto-progress links, in its own link order."""
    live = flagged(waiter)
    return [source for source in library.requires(waiter.id) if source.id in live]


def collectors(library: Library, source: Step) -> list[Step]:
    """The steps that collect ``source`` over an auto-progress link, in project order."""
    return [step for step in library.dependents(source.id) if source.id in flagged(step)]


def remap_for_paste(
    _project: Project, steps: Sequence[Step], remapped: Mapping[StepId, StepId]
) -> None:
    """A copy collects the copies of what its original collected — the paste policy.

    Only the links between copies survive a paste, so only their ids are carried, each
    renamed to its clone's; an entry left naming nothing goes.
    """
    for step in steps:
        entry = write(remapped[source] for source in read(step) if source in remapped)
        if entry:
            step.module_data[MODULE_ID] = entry
        else:
            step.module_data.pop(MODULE_ID, None)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when none of its links auto-progress."""
    count = len(flagged(step))
    return f"auto-progress from {count}" if count else ""


SPEC = AspectSpec(
    id=MODULE_ID,
    label="Auto-progress",
    summary="Which requires links free the step as soon as their source reads ready for"
    " review: the step takes that work, lands it and sets the source done.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
