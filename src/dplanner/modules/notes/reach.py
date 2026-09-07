"""What reaches a step: the derivation every briefing, ``note index`` and the Agent tab read.

**Which notes a step's worker should know is computed, never stored** — the same rule the
topological order follows, and for the same reason: ``dplanner step link`` changes the
graph with no window running to notice, and a stored answer would be wrong the moment it
did. One function answers for all three readers, so they cannot disagree.

The shape is the whole design. A briefing that carried every note in full stopped fitting
in an agent's head at the third handoff, so it carries two things instead: the notes
**addressed to this step** in full — how one agent points the next at exactly what it
must read — and an **index** of everything else that reaches it, one line per note, with
the verb that opens one. What reaches a step is its label's business (:mod:`.log`): a
handoff reaches the steps after the one it was made on, a decision reaches everyone, and
``--reach project`` lifts any note to everyone.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import upstream
from dplanner.domain.schedule import format_date
from dplanner.modules.notes.log import (
    LABELS,
    PROJECT,
    Note,
    reach_of,
    read_log,
    standing,
)

KeyOf = Callable[[Step], str]


@dataclass(frozen=True)
class Index:
    addressed: tuple[Note, ...]  # For this step by name: carried in full.
    listed: tuple[Note, ...]  # Everything else that reaches it: one line each.

    def __bool__(self) -> bool:
        return bool(self.addressed or self.listed)


def reaching(library: Library, step: Step) -> Index:
    """The standing notes that reach ``step``, split into the ones addressed to it and the
    rest, each in log order. A note made on the step itself reaches it too — a re-run of
    the step is a pick-up as much as the next step is."""
    project = library.project_of(step.id)
    behind = {other.id for other in upstream(library, project, step.id)} | {step.id}
    addressed: list[Note] = []
    listed: list[Note] = []
    for note in standing(read_log(project)):
        if step.id in note.for_steps:
            addressed.append(note)
        elif reach_of(note) == PROJECT or note.step in behind:
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


def index_lines(project: Project, notes: tuple[Note, ...], key_of: KeyOf) -> list[str]:
    """The index as markdown: a heading per label, in the ontology's order, one line per
    note under it — id, title, and when and where it was made."""
    lines: list[str] = []
    for label in LABELS:
        group = [note for note in notes if note.label == label.id]
        if not group:
            continue
        lines += [f"{label.group} ({len(group)}):"]
        for note in group:
            facts = when_where(project, note, key_of)
            lines.append(f"- {note.id} · {note.title}" + (f" ({facts})" if facts else ""))
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


def briefing_blocks(project: Project, index: Index, key_of: KeyOf) -> list[Block]:
    """The two sections a briefing carries — worded once, so ``dplanner note index`` prints
    exactly what the agent was launched with."""
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
            f" `dplanner note show {ref} <id>` prints one, `dplanner note add {ref} <label>"
            " <title>` records yours — the DPlanner skill says when.",
            "",
        ]
        lines += index_lines(project, index.listed, key_of)
        blocks.append(Block("Notes so far", "\n".join(lines)))
    return blocks


def project_ref(project: Project) -> str:
    """The project as a verb names it: the title, quoted when it has a space."""
    title = project.title or project.id
    return f"'{title}'" if " " in title else title
