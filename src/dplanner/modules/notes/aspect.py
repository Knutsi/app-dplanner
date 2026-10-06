"""The notes aspect: the record shape, its labels, the one place it is read and written,
and which notes reach a step.

A **note** is a fact the graph cannot derive and the diff does not explain: why the plan
went one way rather than another, what a finished step wants the next worker to know,
where the work departed from the spec, what was noticed and put off. Left in a commit
message it is found by archaeology; left in an agent's transcript it is gone with the
session. So it is a record beside the project — ``modules/notes.json``, a list the way
a project's test runs are a list — and every briefing carries an *index* of the ones that
reach the step (:func:`reaching`), so the hundredth agent finds what the first
ninety-nine left without reading all of it.

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
note, and :func:`adding` is how ``note add`` and ``status set --because`` both keep to
it — on the same step, so two steps may each leave a note by the same bad title without one
being lost. (The window's *Add Note* mints a fresh, untitled one each time, on purpose.)
Everything here is Qt-free and shared by the verbs and the card verbatim, so no two
surfaces can disagree about what a note is.

**Which notes a step's worker should know is computed, never stored** — what every briefing,
``note index`` and the Agent tab read — the same rule the
topological order follows, and for the same reason: ``dplanner step link`` changes the
graph with no window running to notice, and a stored answer would be wrong the moment it
did. One function answers for all three readers, so they cannot disagree.

The shape is the whole design, and it was settled twice. A briefing that carried every note
in full stopped fitting in an agent's head at the third handoff, so it carries two things
instead: the notes **addressed to this step** in full — how one agent points the next at
exactly what it must read — and an **index** of everything else that reaches it, one line
per note, with the verb that opens one. Then a 320-note plan showed that an *index* of
everything grows the same way: it came to 73% of every briefing, and 267 of its lines were
identical on all 57 agent steps. So two rules bound it. **The graph says who a note is
for** — every label reaches the steps after the one it was made on (:func:`reach_of`),
and ``--reach project`` lifts the one note that binds the whole plan. And the index lists
at most :data:`INDEX_LIMIT` per label, newest kept, **saying what it left out** and the
verb that reads the rest — a ceiling, so a plan twice as long does not undo the first rule.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
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
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ids import next_id
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import upstream
from dplanner.domain.store import FilesFor
from dplanner.planning.dates import format_date

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


def adding(project: Project, draft: Note) -> tuple[Note, SetModuleDataCommand | None]:
    """``draft`` as the project's next note, and the command that appends it to the log — or
    the note the step already carries by that title, and None: adding twice is one note.
    The one way a verb adds a note, so every verb mints the id and keeps that rule."""
    records = read_log(project)
    existing = same_note(records, draft.title, draft.step)
    if existing is not None:
        return existing, None
    note = replace(draft, id=next_note_id(records))
    return note, SetModuleDataCommand(project.id, MODULE_ID, write_log([*records, note]))


def note_on(
    project: Project, step: Step, label_id: str, title: str, body: str, day: date
) -> tuple[str, SetModuleDataCommand | None]:
    """A ``label_id`` note made on ``step`` on ``day``, through :func:`adding`: its id, and the
    command that adds it — None when the step already carries it, so a retried verb is one
    note. How a workflow keeps what a person must read: a reason, an escalation."""
    note, command = adding(
        project,
        Note(
            id="",
            label=check_label(label_id),
            title=title,
            body=body,
            made=day.isoformat(),
            step=step.id,
        ),
    )
    return note.id, command


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


KeyOf = Callable[[Step], str]

# How many notes one label's group lists before it starts naming what it left out. A
# briefing is read once, from the top: an index nobody finishes costs what a log costs.
# Measured on a 74-step plan with 320 standing notes — see docs/architecture/decisions.md.
INDEX_LIMIT = 20


@dataclass(frozen=True)
class Index:
    addressed: tuple[Note, ...]  # For this step by name: carried in full.
    listed: tuple[Note, ...]  # Everything else that reaches it: one line each.

    def __bool__(self) -> bool:
        return bool(self.addressed or self.listed)


def reaching(library: Library, step: Step) -> Index:
    """The standing notes that reach ``step``, split into the ones addressed to it and the
    rest, each in log order. A note made on the step itself reaches it too — a re-run of
    the step is a pick-up as much as the next step is.

    A note whose step is **gone** reaches everyone, for the reason a note made on no step
    does: there is nothing left to be downstream of, and a decision does not stop standing
    because the step that made it was deleted.
    """
    project = library.project_of(step.id)
    behind = {other.id for other in upstream(library, project, step.id)} | {step.id}
    live = {other.id for other in project.steps}  # Once per walk: Project.step() is a scan.
    addressed: list[Note] = []
    listed: list[Note] = []
    for note in standing(read_log(project)):
        if step.id in note.for_steps:
            addressed.append(note)
        elif reach_of(note) == PROJECT or note.step in behind or note.step not in live:
            listed.append(note)
    return Index(tuple(addressed), tuple(listed))


def when_where(project: Project, note: Note, key_of: KeyOf) -> str:
    """The facts beside a title — ``5 September, on S7`` — worded once for every reader."""
    facts = []
    if note.made:
        facts.append(day(note.made))
    step = project.step(note.step) if note.step else None
    if step is not None:
        facts.append(f"on {key_of(step) or step.title}")
    return ", ".join(facts)


def day(made: str) -> str:
    try:
        return format_date(date.fromisoformat(made))
    except ValueError:
        return made


@dataclass(frozen=True)
class Group:
    """One label's slice of an index: what it names, and how many it left out."""

    label: Label
    shown: tuple[Note, ...]
    elided: int


def grouped(notes: tuple[Note, ...], limit: int | None) -> list[Group]:
    """Per label, in the ontology's order: the notes an index would name and how many it
    left out. The one place the cap is applied, so the rendered index and ``note index
    --json`` can never name different notes. A label with nothing is absent."""
    groups: list[Group] = []
    for label in LABELS:
        group = [note for note in notes if note.label == label.id]
        if not group:
            continue
        shown = group if limit is None else group[-limit:]
        groups.append(Group(label, tuple(shown), len(group) - len(shown)))
    return groups


def listed_within(notes: tuple[Note, ...], limit: int | None) -> tuple[Note, ...]:
    """The notes an index of ``notes`` actually names, in log order."""
    kept = {note.id for group in grouped(notes, limit) for note in group.shown}
    return tuple(note for note in notes if note.id in kept)


def index_lines(
    project: Project,
    notes: tuple[Note, ...],
    key_of: KeyOf,
    limit: int | None = INDEX_LIMIT,
) -> list[str]:
    """The index as markdown: a heading per label, in the ontology's order, one line per
    note under it — id, title, and when and where it was made.

    A group past ``limit`` keeps its newest and says so: the heading counts both numbers and
    the group closes with the verb that reads the rest. ``None`` lists everything.
    """
    lines: list[str] = []
    for group in grouped(notes, limit):
        total = len(group.shown) + group.elided
        counted = f"{len(group.shown)} of {total}" if group.elided else str(total)
        lines += [f"{group.label.group} ({counted}):"]
        for note in group.shown:
            facts = when_where(project, note, key_of)
            lines.append(f"- {note.id} · {note.title}" + (f" ({facts})" if facts else ""))
        if group.elided:
            lines.append(
                f"…and {group.elided} earlier: `dplanner note list {project_ref(project)}"
                f" --label {group.label.id}`"
            )
        lines.append("")
    return lines[:-1] if lines else lines


def full_lines(project: Project, note: Note, key_of: KeyOf) -> list[str]:
    """One note in full, as the briefing and ``note show`` print it."""
    facts = when_where(project, note, key_of)
    head = f"**{note.id} {note.label} · {note.title}**" + (f" ({facts})" if facts else "")
    lines = [f"- {head}"]
    lines += [f"  {line}" if line else "" for line in note.body.rstrip().splitlines()]
    return lines


@dataclass(frozen=True)
class Block:
    """One briefing section: what it is called, its markdown, and the notes it prints in
    full — so a caller can carry the files those bodies link."""

    heading: str
    body: str
    carried: tuple[Note, ...] = ()


def briefing_blocks(
    project: Project, index: Index, key_of: KeyOf, limit: int | None = INDEX_LIMIT
) -> list[Block]:
    """The two sections a briefing carries — worded once, so ``dplanner note index`` prints
    exactly what the agent was launched with. ``limit`` is the index's per-label ceiling,
    ``None`` for the whole of it (``note index --all``)."""
    blocks: list[Block] = []
    ref = project_ref(project)
    if index.addressed:
        lines = ["Earlier work addressed these to this step — read them before you start.", ""]
        for note in index.addressed:
            lines += full_lines(project, note, key_of)
        blocks.append(Block("Notes for this step", "\n".join(lines), index.addressed))
    if index.listed:
        lines = [
            "The project's record of what was decided and handed on, one line each. Read the"
            " ones that touch your work before you start; every note carries its reasoning."
            f" `dplanner note show {ref} <id>` prints one and `dplanner note list {ref}` the"
            " whole log — this index is what reaches *this* step, keeping the most recent"
            f" where a label has many. `dplanner note add {ref} <label> <title>` records"
            " yours — the DPlanner skill says when.",
            "",
        ]
        lines += index_lines(project, index.listed, key_of, limit)
        blocks.append(Block("Notes so far", "\n".join(lines)))
    return blocks


def project_ref(project: Project) -> str:
    """The project as a verb names it: the title, quoted when it has a space."""
    title = project.title or project.id
    return f"'{title}'" if " " in title else title
