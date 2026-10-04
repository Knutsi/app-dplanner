"""How the project's feature catalogue became each feature step's own entry.

Format 2 kept a **record** beside the project — ``modules/feature.json``, one row per
feature with its title, description, images and the spec passages it was read from — and
beside the step only that record's id. Format 3 has no record: the step's title is the
feature's name, its description is the feature's description, its file area holds the
pictures, and the passages are the step's own entry.

That moves data between *owners*, which a per-entry converter cannot do — it never sees the
project — so this is the format's ``absorb`` pass (``core/module_data.py``), run once per
open over the repository and the loaded library. ``modules/notes/migrate.py`` is the other
one, and the file-moving half is lifted from it.

**A migration spells the shapes it moves between.** Nothing here imports :mod:`.aspect`:
the old rows and the new entry are written out literally, so a later change to what
``write()`` produces cannot retroactively change what a format-2 file becomes. It is also
what keeps the import between these two files pointing one way.

Three things are worth knowing before changing it:

**A created step's data goes on the ``Step`` before ``add_child``, and its id is never
returned.** The builder flushes the ids an absorption returns with the ``module_data`` and
``module_text`` aspects only, and a step that did not exist a moment ago has no directory
recorded yet — returning its id raises deep inside the store rather than failing a test.
``add_child`` marks the *project* structurally dirty, and that is what writes the subtree.

**The shelf is reached from here.** ``domain/shelf.py``'s ``migrate_shelved`` runs after
this pass and walks a shelved entry through the per-entry chain, which for a shelved
feature marker is a pass-through — so a marker shelved at format 2 would be stamped to 3
with its record id still in it and its passages lost. It is rewritten here instead.

**It writes into a living module's namespace.** The record's description becomes the step's
``step_description`` prose, its opt-out is lifted and its images land in that module's file
area — named by a string constant, never an import, because a module may not import
another. The alternative, keeping a description inside the feature entry, would re-create
exactly the duplication format 3 exists to remove. ``FORMAT.md`` has the rule.

Idempotent by construction: after one run no project holds ``"features"`` and no step's
entry holds a record id, which is the test the pass makes before it does anything.
"""

import mimetypes
from pathlib import PurePosixPath
from typing import Any

from dplanner.core.repository import FileArea, Repository
from dplanner.domain.assets import asset_name
from dplanner.domain.model import Library, Project, Step

MODULE_ID = "feature"
FORMAT_VERSION = 3

# The format-2 keys this pass reads: the catalogue beside a project, the record id beside
# a step. Spelled here rather than imported — see the module docstring.
RECORDS_KEY = "features"
RECORD_KEY = "feature"

# The living module whose prose and pictures a record's description and images become.
DESCRIPTION_ID = "step_description"

SHELF_ID = "shelf"
SHELF_ASPECTS = "aspects"


def absorb_catalogue(repo: Repository[Any], library: Library) -> list[str]:
    """Every project's catalogue onto its steps — see the module docstring.

    Everything the pass reads is read *before* anything is written: a step rewritten at
    format 3 no longer names a record, so a second look would take it for a marker and
    write its passages away.
    """
    changed: list[str] = []
    for project in library.projects:
        rows = _rows(project)
        instances = _instances(project)
        shelved = _shelved_records(project)
        if not rows and not instances and not shelved and MODULE_ID not in project.module_data:
            continue  # Migrated already, or never had a catalogue: nothing to do.
        changed += _rewrite_shelves(repo, project, {row["id"]: row.get("sources") for row in rows})
        for row in rows:
            steps = instances.get(row["id"], [])
            for step in steps:
                repo.set_module_data(step.id, MODULE_ID, _entry(row.get("sources")))
                changed.append(step.id)
            if steps:
                # The prose and the pictures are one record's, so they go to one step —
                # the first, where a hand edit left two claiming the same record.
                _absorb_prose(repo, library, project, row, steps[0])
            elif row["id"] not in shelved:
                _born(repo, library, project, row)
        known = {row["id"] for row in rows}
        for record_id, steps in instances.items():
            if record_id in known:
                continue
            # A marker naming a record the catalogue never held — what `feature.dangling`
            # reported. It was always a feature to the graph, and now it is one that cites
            # nothing, which is a whole answer rather than a finding.
            for step in steps:
                repo.set_module_data(step.id, MODULE_ID, _entry(None))
                changed.append(step.id)
        if MODULE_ID in project.module_data:
            repo.set_module_data(project.id, MODULE_ID, {})
            changed.append(project.id)
    return changed


# -- reading what format 2 wrote ----------------------------------------------------------------


def _rows(project: Project) -> list[dict[str, Any]]:
    """The catalogue rows, at format 2 — unreadable rows read as absent."""
    raw = (project.module_data.get(MODULE_ID) or {}).get(RECORDS_KEY)
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict) and isinstance(row.get("id"), str)]


def _record_id(entry: dict[str, Any] | None) -> str:
    """The record a format-2 marker names, or "" for one that names none."""
    record = (entry or {}).get(RECORD_KEY)
    return record if isinstance(record, str) else ""


def _instances(project: Project) -> dict[str, list[Step]]:
    """Record id → the steps naming it. One is the rule; two was a lint finding."""
    found: dict[str, list[Step]] = {}
    for step in project.steps:
        record = _record_id(step.module_data.get(MODULE_ID))
        if record:
            found.setdefault(record, []).append(step)
    return found


# -- writing format 3 ---------------------------------------------------------------------------


def _entry(sources: Any) -> dict[str, Any]:
    """The format-3 entry, written literally: on, and the passages when there are any."""
    entry: dict[str, Any] = {"on": True, "format": FORMAT_VERSION}
    rows = [row for row in sources if isinstance(row, dict)] if isinstance(sources, list) else []
    if rows:
        entry["cites"] = rows
    return entry


def _born(repo: Repository[Any], library: Library, project: Project, row: dict[str, Any]) -> None:
    """A record nobody placed, as the step it always meant to be.

    Its entry is set on the object before ``add_child`` and its id is never returned — the
    module docstring says why. No position is written: nothing was pointed at, so the
    ambient layout places it, which is what *an explicit sort persists and the ambient
    layout never does* asks of a step nobody put anywhere. Its prose and pictures then
    arrive by the same path a placed record's do, and the title line never fires, because
    the step is titled from the record.
    """
    step = Step(title=str(row.get("title") or "") or "Untitled feature")
    step.module_data[MODULE_ID] = _entry(row.get("sources"))
    library.add_child(project.id, step)
    _absorb_prose(repo, library, project, row, step)


def _absorb_prose(
    repo: Repository[Any], library: Library, project: Project, row: dict[str, Any], step: Step
) -> None:
    """The record's title line, description and images onto the step that realises it.

    The step's own title wins — it is the feature's name now — so a record titled
    differently is not lost but recorded in a line above the prose. A step that had opted
    *out* of a description and is given one has its opt-out lifted, or the prose would be
    written where nothing shows it.
    """
    lines = []
    title = str(row.get("title") or "")
    if title and title != step.title:
        lines.append(f"*Catalogued as \u201c{title}\u201d.*")
    description = str(row.get("description") or "")
    existing = library.text(step.id, DESCRIPTION_ID).rstrip()
    if description and description.strip() not in existing:
        lines.append(description)
    lines += _moved_images(repo, project, step, row)
    if not lines:
        return
    library.set_text(
        step.id, DESCRIPTION_ID, "\n\n".join([*lines, existing] if existing else lines)
    )
    _lift_opt_out(repo, step)


def _lift_opt_out(repo: Repository[Any], step: Step) -> None:
    entry = step.module_data.get(DESCRIPTION_ID)
    if entry and entry.get("off"):
        repo.set_module_data(step.id, DESCRIPTION_ID, {})


def _moved_images(
    repo: Repository[Any], project: Project, step: Step, row: dict[str, Any]
) -> list[str]:
    """The record's pictures out of the project's feature area and into the step's, as the
    markdown links that now keep them alive.

    Content-addressed on the way, like every attach — a picture nothing links to is what
    ``asset prune`` sweeps, and these were shown by the record's own editor rather than by
    a link.
    """
    names = [name for name in row.get("images", ()) if isinstance(name, str)]
    if not names:
        return []
    old_area = _area(repo, project.id, MODULE_ID)
    new_area = _area(repo, step.id, DESCRIPTION_ID)
    if old_area is None or new_area is None:
        return []
    links = []
    for name in sorted(names):
        data = old_area.read_bytes(name)
        if data is None:
            continue
        linked = asset_name(data, PurePosixPath(name).name)
        new_area.write_bytes(linked, data)
        old_area.remove(name)
        mime = mimetypes.guess_type(name)[0] or ""
        stem = PurePosixPath(name).stem
        links.append(f"![{stem}]({linked})" if mime.startswith("image/") else f"[{stem}]({linked})")
    return ["\n".join(links)] if links else []


# -- the shelf ----------------------------------------------------------------------------------


def _shelved_records(project: Project) -> set[str]:
    """The records a shelved marker names — a feature somebody turned off."""
    found = set()
    for step in project.steps:
        entry = (step.module_data.get(SHELF_ID) or {}).get(SHELF_ASPECTS, {}).get(MODULE_ID)
        record = _record_id((entry or {}).get("data"))
        if record:
            found.add(record)
    return found


def _rewrite_shelves(repo: Repository[Any], project: Project, cites: dict[str, Any]) -> list[str]:
    """Shelved feature markers at format 3, carrying their record's passages with them."""
    changed = []
    for step in project.steps:
        shelf = step.module_data.get(SHELF_ID)
        if not shelf:
            continue
        aspects = {key: dict(entry) for key, entry in shelf.get(SHELF_ASPECTS, {}).items()}
        kept = aspects.get(MODULE_ID)
        record = _record_id((kept or {}).get("data"))
        if kept is None or not record:
            continue
        kept["data"] = _entry(cites.get(record))
        aspects[MODULE_ID] = kept
        repo.set_module_data(step.id, SHELF_ID, {SHELF_ASPECTS: aspects, "format": 1})
        changed.append(step.id)
    return changed


def _area(repo: Repository[Any], owner_id: str, module_id: str) -> FileArea | None:
    try:
        return repo.files(owner_id, module_id)
    except KeyError:
        return None  # A node the store has never flushed has no directory yet.
