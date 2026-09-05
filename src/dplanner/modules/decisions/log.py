"""The decision log: the record shape, and the one place it is read and written.

A decision is a fact the graph cannot derive and the diff does not explain: *why* the
plan went one way rather than another. Left in a commit message it is found by
archaeology; left in an agent's transcript it is gone with the session. So it is a
record beside the project — ``modules/decisions.json``, a list the way the feature
catalogue is a list — and every agent's briefing carries the standing ones, which is
what stops the fourth agent re-deciding what the first three settled.

**A decision has an id, a title, a body, a day, and where it was made.** The id (``D1``,
``D2``, …) is minted per project and never reused, so a later decision can name the one
it *supersedes* — a reversal is a new record pointing at the old, never an edit that
loses the history. ``step`` is the step the decision was taken on, when there was one;
a project-wide convention carries none. The body is markdown in the record, the shape
``testing`` and ``feature`` settled on for N documents per node.

**Adding twice is not two decisions.** An agent re-runs a command after a stale-workspace
refusal, or an epilogue runs again; a title already in the log is *that* decision, and
``same_title`` is how ``decision add`` and the card both say so. Everything here is Qt-free
and shared by the verbs and the card verbatim, so no two surfaces can disagree about what
a decision is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.cli.command import CliError
from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.ids import next_id
from dplanner.domain.model import Project

MODULE_ID = "decisions"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
RECORDS_KEY = "decisions"
ID_PREFIX = "D"


@dataclass(frozen=True)
class Decision:
    id: str  # "D1", "D2", … — what every verb, a briefing and a supersedes link address.
    title: str
    body: str = ""  # Markdown, a string in the record: the reasoning and the options.
    made: str = ""  # The day it was taken, ISO; "" when nobody said.
    step: str = ""  # The step it was taken on, by id; "" for a project-wide decision.
    supersedes: str = ""  # An earlier decision this one reverses or replaces.


def read_log(project: Project) -> list[Decision]:
    """The decisions beside ``project``, oldest first. Unreadable rows read as absent."""
    entry = project.module_data.get(MODULE_ID, {})
    raw = entry.get(RECORDS_KEY)
    if not isinstance(raw, list):
        return []
    return [
        Decision(
            id=row["id"],
            title=str(row.get("title", "")),
            body=str(row.get("body", "") or ""),
            made=str(row.get("made", "") or ""),
            step=str(row.get("step", "") or ""),
            supersedes=str(row.get("supersedes", "") or ""),
        )
        for row in raw
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def write_log(records: Sequence[Decision]) -> dict[str, Any]:
    """The entry for these records — ``{}`` (remove the file) when there are none. Every
    key but the id and the title is omitted when empty, FORMAT.md's absence rule."""
    if not records:
        return {}
    rows = []
    for record in records:
        row: dict[str, Any] = {"id": record.id, "title": record.title}
        for key in ("body", "made", "step", "supersedes"):
            if getattr(record, key):
                row[key] = getattr(record, key)
        rows.append(row)
    return stamped({RECORDS_KEY: rows}, DATA_FORMAT.version)


def next_decision_id(records: Sequence[Decision]) -> str:
    return next_id([record.id for record in records], ID_PREFIX)


def same_title(records: Sequence[Decision], title: str) -> Decision | None:
    """The record already carrying ``title`` — case and surrounding space aside — or None.
    What makes recording a decision twice one decision."""
    wanted = title.strip().lower()
    return next((record for record in records if record.title.strip().lower() == wanted), None)


def find_decision(project: Project, needle: str) -> Decision:
    """The decision ``needle`` names: its id (``D3``, ``d3``), else a unique part of its
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
        raise CliError(
            f"no decision {needle!r} in {project.title!r} — see `dplanner decision list`"
        )
    listed = ", ".join(f"{record.id} ({record.title})" for record in partial)
    raise CliError(f"{needle!r} matches several decisions: {listed}")


def with_decision(records: Sequence[Decision], updated: Decision) -> list[Decision]:
    """``records`` with ``updated`` in place of the record sharing its id."""
    return [updated if record.id == updated.id else record for record in records]


def without_decision(records: Sequence[Decision], decision_id: str) -> list[Decision]:
    return [record for record in records if record.id != decision_id]


def superseded_ids(records: Sequence[Decision]) -> set[str]:
    """The decisions a later one replaced — what a briefing leaves out."""
    return {record.supersedes for record in records if record.supersedes}


def standing(records: Sequence[Decision]) -> list[Decision]:
    """The decisions still in force: everything nothing later superseded."""
    gone = superseded_ids(records)
    return [record for record in records if record.id not in gone]
