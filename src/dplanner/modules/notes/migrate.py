"""How the two modules this one retired reach the log: the decision log by takeover, the
handoff aspect by absorption.

**Decisions** were already a record list on the project — ``modules/decisions.json`` — so
they are a :class:`~dplanner.core.module_data.Takeover`: the retired id and its frozen
format live here, and :func:`from_decisions` rewrites each ``D<n>`` as ``N<n>`` wearing
the ``decision`` label, supersedes links with it.

**Handoffs** were prose and files on each *step* (``step_handoff.md``, a scope in
``step_handoff.json``, an area of attachments), and a per-entry converter never sees the
project the record belongs on — so they are the format's ``absorb`` pass:
:func:`absorb_handoffs` walks every project once per open, turns each step's handoff into
a ``handoff`` note made on that step (a project-wide scope becomes ``reach: project``),
copies its files into the project's notes area and links them from the body, and clears
the step's entries. Idempotent by construction: a second open finds nothing to move. A
handoff a person had turned *off* sits in the step's shelf under the retired id; it stays
there untouched, which is what a turned-off aspect was for.
"""

import mimetypes
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover
from dplanner.core.repository import FileArea, Repository
from dplanner.domain.assets import ASSETS_DIR, asset_name
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.notes.log import (
    FORMAT_VERSION,
    ID_PREFIX,
    MODULE_ID,
    PROJECT,
    Note,
    entry_rows,
    next_note_id,
    notes_in,
    read_log,
    write_log,
)

RETIRED_DECISIONS = ModuleDataFormat("decisions")  # Format 1 was the last it wrote.
RETIRED_HANDOFF_ID = "step_handoff"
TITLE_LIMIT = 80


def from_decisions(retired: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """The decision log as notes, after whatever the notes entry already holds."""
    kept = notes_in(existing)
    rows = _rows(retired)
    start = int(next_note_id(kept)[len(ID_PREFIX) :])
    ids = {row["id"]: f"{ID_PREFIX}{start + offset}" for offset, row in enumerate(rows)}
    converted = [
        Note(
            id=ids[row["id"]],
            label="decision",
            title=str(row.get("title", "")),
            body=str(row.get("body", "") or ""),
            made=str(row.get("made", "") or ""),
            step=str(row.get("step", "") or ""),
            supersedes=ids.get(str(row.get("supersedes", "") or ""), ""),
        )
        for row in rows
    ]
    return entry_rows([*kept, *converted])


def absorb_handoffs(repo: Repository[Any], library: Library) -> list[str]:
    """Every step's handoff into its project's log — see the module docstring."""
    changed: list[str] = []
    for project in library.projects:
        records = read_log(project)
        touched_project = False
        for step in project.steps:
            note = _handoff_note(repo, library, project, step, records)
            if note is not None:
                records = [*records, note]
                touched_project = True
            if _cleared(repo, library, step):
                changed.append(step.id)
        if touched_project:
            repo.set_module_data(project.id, MODULE_ID, write_log(records))
            changed.append(project.id)
    return changed


def _handoff_note(
    repo: Repository[Any], library: Library, project: Project, step: Step, records: Sequence[Note]
) -> Note | None:
    body = library.text(step.id, RETIRED_HANDOFF_ID).rstrip()
    scope = (step.module_data.get(RETIRED_HANDOFF_ID) or {}).get("scope")
    old_area = _area(repo, step.id, RETIRED_HANDOFF_ID)
    names = old_area.names(ASSETS_DIR) if old_area is not None else []
    if not body and not names:
        return None
    if names and old_area is not None:
        body = _move_files(repo, project, old_area, names, body)
    return Note(
        id=next_note_id(records),
        label="handoff",
        title=_title_from(body) or f"Handoff from {step.title or 'an untitled step'}",
        body=body,
        step=step.id,
        reach=PROJECT if scope == PROJECT else "",
    )


def _move_files(
    repo: Repository[Any], project: Project, old_area: FileArea, names: list[str], body: str
) -> str:
    new_area = _area(repo, project.id, MODULE_ID)
    if new_area is None:
        return body
    links = []
    for name in sorted(names):
        data = old_area.read_bytes(f"{ASSETS_DIR}/{name}")
        if data is None:
            continue
        linked = asset_name(data, name)
        new_area.write_bytes(linked, data)
        old_area.remove(f"{ASSETS_DIR}/{name}")
        mime = mimetypes.guess_type(name)[0] or ""
        stem = PurePosixPath(name).stem
        links.append(f"![{stem}]({linked})" if mime.startswith("image/") else f"[{name}]({linked})")
    if not links:
        return body
    return (body + "\n\n" if body else "") + "\n".join(links)


def _cleared(repo: Repository[Any], library: Library, step: Step) -> bool:
    """Take the retired entries off the step; True when there was something to take."""
    had = bool(library.text(step.id, RETIRED_HANDOFF_ID)) or RETIRED_HANDOFF_ID in step.module_data
    if library.text(step.id, RETIRED_HANDOFF_ID):
        library.set_text(step.id, RETIRED_HANDOFF_ID, "")
    if RETIRED_HANDOFF_ID in step.module_data:
        repo.set_module_data(step.id, RETIRED_HANDOFF_ID, {})
    return had


def _area(repo: Repository[Any], owner_id: str, module_id: str) -> FileArea | None:
    try:
        return repo.files(owner_id, module_id)
    except KeyError:
        return None  # A node the store has never flushed has no directory yet.


def _title_from(body: str) -> str:
    """The first line of a handoff as its title: markdown marks off, cut at a word."""
    for line in body.splitlines():
        text = line.strip().lstrip("#-*> ").strip()
        if not text:
            continue
        if len(text) <= TITLE_LIMIT:
            return text
        cut = text[:TITLE_LIMIT].rsplit(" ", 1)[0]
        return f"{cut}…"
    return ""


def _rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entry.get("decisions")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict) and isinstance(row.get("id"), str)]


# Last, because it names the pieces above: the one declaration everything reads.
DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
    version=FORMAT_VERSION,
    takeovers=(Takeover(retired=RETIRED_DECISIONS, convert=from_decisions),),
    absorb=absorb_handoffs,
)
