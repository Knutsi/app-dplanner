"""A timeline written into a library a day at a time, and read the way the window reads it.

:class:`Replay` holds one in-memory project and writes each day of a timeline into it
through the owners' writers (``frames.apply``), then reads the forecast back through the
owners' readers — at the day's end, since a simulated day is over when it is read. What the
recorder would have written is played here too (:func:`record`): the window's recorder, on
the days the window was open, as a row in the project's own history.

**A day can be gone back to.** :func:`keep` copies what the project holds at a day's end —
its steps, their links and every module's entry, exactly as the writers left them — and
:func:`restore` makes a project hold that again, writing only what differs. So a view of
one project can be scrubbed through a timeline in either direction without ever being
handed another project, and without this file knowing what any entry means.
"""

import copy
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Node, Project, Step
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.progress import (
    HISTORY_ID,
    Snapshot,
    recorded,
    saved_with,
    write_history,
)
from dplanner.modules.time_estimates.simulation.frames import Frame, Writers, apply
from dplanner.modules.time_estimates.simulation.timeline import Cadence, Timeline, recorder_ran


@dataclass(frozen=True)
class KeptStep:
    id: str
    title: str
    number: int
    created: str
    requires: tuple[str, ...]
    module_data: Mapping[str, dict[str, Any]]


@dataclass(frozen=True)
class Kept:
    """What a project held at one day's end."""

    module_data: Mapping[str, dict[str, Any]]
    steps: tuple[KeptStep, ...]


def keep(project: Project) -> Kept:
    return Kept(
        module_data=copy.deepcopy(project.module_data),
        steps=tuple(
            KeptStep(
                id=step.id,
                title=step.title,
                number=step.number,
                created=step.created,
                requires=tuple(step.edges.get("requires", [])),
                module_data=copy.deepcopy(step.module_data),
            )
            for step in project.steps
        ),
    )


def restore(library: Library, project: Project, kept: Kept) -> None:
    """Make ``project`` hold what ``kept`` does, writing only what differs: every step
    there first, so a link may name one kept after it, then the links and the entries. A
    step by the same id but another name, number or birthday is another step — another
    seed's plan — and is replaced rather than patched."""
    wanted = {held.id: held for held in kept.steps}
    for step in list(project.steps):
        held = wanted.get(step.id)
        if held is None or (step.title, step.number, step.created) != (
            held.title,
            held.number,
            held.created,
        ):
            RemoveNodeCommand(step.id).redo(library)
    for index, held in enumerate(kept.steps):
        if project.step(held.id) is None:
            born = Step(node_id=held.id, title=held.title, number=held.number, created=held.created)
            AddNodeCommand(project.id, born, index).redo(library)
    for held in kept.steps:
        present = project.step(held.id)
        assert present is not None
        if tuple(present.edges.get("requires", [])) != held.requires:
            SetEdgesCommand(present.id, "requires", list(held.requires)).redo(library)
        _restore_entries(library, present, held.module_data)
    _restore_entries(library, project, kept.module_data)


def _restore_entries(library: Library, node: Node, entries: Mapping[str, dict[str, Any]]) -> None:
    for module_id in sorted(set(node.module_data) | set(entries)):
        entry = entries.get(module_id, {})
        if node.module_data.get(module_id, {}) != entry:
            SetModuleDataCommand(node.id, module_id, copy.deepcopy(entry)).redo(library)


class Replay:
    """One project a timeline is written into, and read back from, a day at a time."""

    def __init__(self, title: str, writers: Writers, readers: Readers) -> None:
        self.library = Library()
        self.project = Project(title=title)
        self.library.add_child(self.library.id, self.project)
        self._writers = writers
        self._readers = readers

    def apply(self, frame: Frame) -> None:
        apply(self.library, self.project, frame, self._writers)

    def forecast(self, day: date) -> Snapshot | None:
        """The plan as the recorder takes it at the end of ``day``."""
        return self._readers.snapshot(self.library, self.project, day, day_over=True)

    def write_history(self, rows: Sequence[Snapshot], saved: Sequence[Snapshot]) -> None:
        """The project's history as the recorder leaves it — directly, as it writes one."""
        SetModuleDataCommand(self.project.id, HISTORY_ID, write_history(rows, saved)).redo(
            self.library
        )


@dataclass(frozen=True)
class SavedSpec:
    """A snapshot somebody saves on purpose, ``after`` days since work began."""

    after: int
    title: str
    note: str


@dataclass(frozen=True)
class Recorded:
    """A timeline as DPlanner would have kept it: what the project held at each day's end,
    the history the recorder had written by then included, and every row it wrote."""

    days: tuple[Kept, ...]  # One per day of the timeline.
    rows: tuple[Snapshot, ...]
    saved: tuple[Snapshot, ...]


def record(
    timeline: Timeline,
    replay: Replay,
    *,
    cadence: Cadence,
    seed: int,
    saved: Sequence[SavedSpec] = (),
) -> Recorded:
    """``timeline`` written into ``replay`` day by day, with the recorder's rows on the days
    the window was open (``cadence``) and each of ``saved`` kept on its day — the window's
    recorder and *Save snapshot…*, played over days that are over."""
    rows: list[Snapshot] = []
    kept: list[Snapshot] = []
    days: list[Kept] = []
    for played, frame in zip(timeline.days, timeline.frames(), strict=True):
        replay.apply(frame)
        due = [one for one in saved if timeline.begin + timedelta(days=one.after) == played.day]
        ran = recorder_ran(cadence, played.day, seed)
        taken = replay.forecast(played.day) if ran or due else None
        if taken is not None:
            if ran:
                rows = recorded(rows, taken) or rows
            for one in due:
                # A title taken twice keeps the first, as the Save Snapshot dialog refuses it.
                with suppress(ValueError):
                    kept = saved_with(kept, taken, one.title, one.note)
            replay.write_history(rows, kept)
        days.append(keep(replay.project))
    return Recorded(tuple(days), tuple(rows), tuple(kept))
