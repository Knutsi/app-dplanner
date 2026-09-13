"""The note log: the record shape, its labels, and the one place it is read and written.

A **note** is a fact the graph cannot derive and the diff does not explain: why the plan
went one way rather than another, what a finished step wants the next worker to know,
where the work departed from the spec, what was noticed and put off. Left in a commit
message it is found by archaeology; left in an agent's transcript it is gone with the
session. So it is a record beside the project — ``modules/notes.json``, a list the way
the feature catalogue is a list — and every briefing carries an *index* of the ones that
reach the step (:mod:`.reach`), so the hundredth agent finds what the first ninety-nine
left without reading all of it.

**A note has an id, a label, a title, a body, a day, where it was made, and who it is
for.** The id (``N1``, ``N2``, …) is minted per project and never reused, so a later note
can name the one it *supersedes* — a reversal is a new record pointing at the old, never
an edit that loses the history. The label is one word from :data:`LABELS`, a closed list
so an agent reading the index knows what each line *is* without opening it. ``step`` is
the step it was made on, when there was one; ``for_steps`` names the steps whose
briefing should carry it in full — how one agent points the next at exactly what it must
read. The body is markdown in the record, the shape ``testing`` and ``feature`` settled on
for N documents per node; files it links live in the module's area beside the project.

**Adding twice is not two notes.** An agent re-runs a command after a stale-workspace
refusal, or an epilogue runs again; a title already in the log *on the same step* is that
note, and :func:`same_note` is how ``note add`` and the card both say so — on the same
step, so two steps may each leave a note by the same bad title without one being lost.
Everything here is Qt-free and shared by the verbs and the card verbatim, so no two
surfaces can disagree about what a note is.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from dplanner.cli.command import CliError
from dplanner.core.module_data import stamped
from dplanner.domain.assets import (
    AssetLocation,
    AssetSource,
    AssetUse,
    area_assets,
    asset_references,
)
from dplanner.domain.ids import next_id
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor

MODULE_ID = "notes"
RECORDS_KEY = "notes"
ID_PREFIX = "N"

# Who a note reaches: the steps after the one it was made on, or every step of the project.
# Downstream is the default for every label — the graph is what says who a note is for —
# and PROJECT is stored on the record only when somebody lifted that one note.
PROJECT: Final = "project"
DOWNSTREAM: Final = "downstream"
REACHES: Final = (DOWNSTREAM, PROJECT)


@dataclass(frozen=True)
class Label:
    id: str
    meaning: str  # One line, printed wherever the list is offered.
    group: str  # The index's heading over the notes wearing it.


# The ontology — closed, so an index line says what the note is. A new kind is a row
# here, and `note add --help`, the skill and the index all follow.
LABELS: Final[tuple[Label, ...]] = (
    Label(
        "decision",
        "a choice and why — stands until a later note supersedes it",
        "Decisions standing",
    ),
    Label(
        "handoff",
        "what whoever picks up after this step needs to know",
        "Handoffs from the steps before this one",
    ),
    Label(
        "spec-change",
        "where the work departed from the spec, so the spec can follow",
        "Spec changes",
    ),
    Label("later", "work noticed and deferred inside this project", "Deferred"),
    Label("post-project", "to do once the project has shipped", "After the project"),
)
LABEL_IDS: Final = tuple(label.id for label in LABELS)
DEFAULT_LABEL: Final = "decision"

FORMAT_VERSION = 1


@dataclass(frozen=True)
class Note:
    id: str  # "N1", "N2", … — what every verb, an index line and a supersedes link address.
    label: str  # One of LABEL_IDS.
    title: str
    body: str = ""  # Markdown, a string in the record.
    made: str = ""  # The day it was written, ISO; "" when nobody said.
    step: str = ""  # The step it was made on, by id; "" for a project-wide note.
    supersedes: str = ""  # An earlier note this one reverses or replaces.
    reach: str = ""  # PROJECT when this one note was lifted; "" is downstream.
    for_steps: tuple[str, ...] = ()  # Steps whose briefing carries this note in full.


def label_of(label_id: str) -> Label:
    """The label a note wears; an id this build does not know reads as the default."""
    return next((label for label in LABELS if label.id == label_id), LABELS[0])


def check_label(label_id: str) -> str:
    """``label_id`` if it is one of :data:`LABELS`; a CliError naming them otherwise."""
    if label_id not in LABEL_IDS:
        raise CliError(f"no such label {label_id!r} — one of: {', '.join(LABEL_IDS)}")
    return label_id


def reach_of(note: Note) -> str:
    """Who the note reaches: the steps after the one it was made on, unless the note itself
    says otherwise. A note made on no step has nothing to be downstream of, so it reaches
    the project whatever it wears — as does one whose step is gone (:func:`.reach.reaching`,
    which is the only place that can know)."""
    if not note.step:
        return PROJECT
    return note.reach if note.reach in REACHES else DOWNSTREAM


def read_log(project: Project) -> list[Note]:
    """The notes beside ``project``, oldest first. Unreadable rows read as absent."""
    return notes_in(project.module_data.get(MODULE_ID, {}))


def notes_in(entry: dict[str, Any]) -> list[Note]:
    """The notes an entry holds — ``read_log`` over a dict, for a migration that has the
    entry and not yet the project."""
    raw = entry.get(RECORDS_KEY)
    if not isinstance(raw, list):
        return []
    return [
        Note(
            id=row["id"],
            label=str(row.get("label", "") or DEFAULT_LABEL),
            title=str(row.get("title", "")),
            body=str(row.get("body", "") or ""),
            made=str(row.get("made", "") or ""),
            step=str(row.get("step", "") or ""),
            supersedes=str(row.get("supersedes", "") or ""),
            reach=str(row.get("reach", "") or ""),
            for_steps=tuple(str(s) for s in row.get("for", ()) if isinstance(s, str)),
        )
        for row in raw
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def write_log(records: Sequence[Note]) -> dict[str, Any]:
    """The entry for these records — ``{}`` (remove the file) when there are none. Every
    key but the id, the label and the title is omitted when empty, FORMAT.md's absence
    rule; the reach is written only when it differs from the default."""
    return stamped(entry_rows(records), FORMAT_VERSION)


def entry_rows(records: Sequence[Note]) -> dict[str, Any]:
    if not records:
        return {}
    rows = []
    for record in records:
        row: dict[str, Any] = {"id": record.id, "label": record.label, "title": record.title}
        for key in ("body", "made", "step", "supersedes"):
            if getattr(record, key):
                row[key] = getattr(record, key)
        if record.reach == PROJECT:  # Downstream is the default, so only the lift is written.
            row["reach"] = record.reach
        if record.for_steps:
            row["for"] = list(record.for_steps)
        rows.append(row)
    return {RECORDS_KEY: rows}


def next_note_id(records: Sequence[Note]) -> str:
    return next_id([record.id for record in records], ID_PREFIX)


def same_note(records: Sequence[Note], title: str, step: str) -> Note | None:
    """The record already carrying ``title`` on ``step`` — case and surrounding space
    aside — or None. What makes recording a note twice one note."""
    wanted = title.strip().lower()
    return next((r for r in records if r.step == step and r.title.strip().lower() == wanted), None)


def find_note(project: Project, needle: str) -> Note:
    """The note ``needle`` names: its id (``N3``, ``n3``), else a unique part of its
    title. Refuses the way ``find_step`` does — an ambiguous name lists the ids."""
    records = read_log(project)
    for record in records:
        if record.id.lower() == needle.strip().lower():
            return record
    lowered = needle.lower()
    exact = [record for record in records if record.title.lower() == lowered]
    partial = exact or [record for record in records if lowered in record.title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise CliError(f"no note {needle!r} in {project.title!r} — see `dplanner note list`")
    listed = ", ".join(f"{record.id} ({record.title})" for record in partial)
    raise CliError(f"{needle!r} matches several notes: {listed}")


def with_note(records: Sequence[Note], updated: Note) -> list[Note]:
    """``records`` with ``updated`` in place of the record sharing its id."""
    return [updated if record.id == updated.id else record for record in records]


def without_note(records: Sequence[Note], note_id: str) -> list[Note]:
    """``records`` without ``note_id`` — and nothing left claiming to supersede it."""
    return [
        replace(record, supersedes="") if record.supersedes == note_id else record
        for record in records
        if record.id != note_id
    ]


def superseded_ids(records: Sequence[Note]) -> set[str]:
    """The notes a later one replaced — what an index leaves out."""
    return {record.supersedes for record in records if record.supersedes}


def standing(records: Sequence[Note]) -> list[Note]:
    """The notes still in force: everything nothing later superseded."""
    gone = superseded_ids(records)
    return [record for record in records if record.id not in gone]


def note_files(files: FilesFor, project_id: str, note: Note) -> tuple[str, ...]:
    """The files the note's body links, as absolute paths — what a briefing carries beside
    it. A project the store has never flushed has no area yet, and that is no files."""
    try:
        area = files(project_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(
        str(area.absolute(name))
        for name in asset_references(note.body)
        if area.read_bytes(name) is not None
    )


def asset_source() -> AssetSource:
    """The log's slice of the project's asset catalog: the files beside the notes.

    A file is used while a note's body links it — ``note attach`` writes the link as it
    copies the file in, and the handoff absorption did the same — so a copy nothing links
    any more is what ``asset prune`` sweeps.
    """

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        used: dict[str, list[AssetUse]] = {}
        for note in read_log(project):
            for name in asset_references(note.body):
                used.setdefault(name, []).append(
                    AssetUse("project", project.id, project.title, f"note {note.id} — {note.title}")
                )
        return [
            AssetLocation(
                node_id=project.id,
                module_id=MODULE_ID,
                name=name,
                uses=tuple(used.get(name, ())),
            )
            for name in area_assets(files, project.id, MODULE_ID)
        ]

    return AssetSource(id=MODULE_ID, label="Notes", scan=scan)
