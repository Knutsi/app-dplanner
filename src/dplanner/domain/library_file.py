"""The project library file: which projects a user is planning, and where their code is.

Per user, per machine — it lives in the Qt-free config directory (see
:mod:`dplanner.core.config_dir`) so the CLI can resolve it without a graphics stack, and it
is never shared through version control: it is a list of *this machine's* paths. The window
and the CLI read the same file, which is what makes ``dplanner`` verbs and the Projects
panel agree about what exists.

The format is deliberately small::

    {
        "format": 2,
        "projects": [{"path": "/home/anna/plans/search", "checkout": "/home/anna/src/widget"}],
    }

Paths are absolute (``~`` is allowed) and the array order is the order the panel shows.
``checkout`` is where this machine has the project's *code* repository — the one per-machine
fact that belongs beside the project directory, absent until something records it (the CLI
does, the first time it is run from that checkout). A format-1 row has no ``checkout`` and
reads the same. Reading is tolerant — a malformed entry is skipped, not fatal — because
this file is edited by two instances and the occasional human, and refusing the whole
library over one bad row would take every healthy project down with it.
"""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic

LIBRARY_ENV = "DPLANNER_LIBRARY"
LIBRARY_FORMAT = 2


@dataclass(frozen=True)
class LibraryEntry:
    """One row: the project directory, and where this machine has its code checked out."""

    path: Path
    checkout: Path | None = None


def default_library_path() -> Path:
    """Where the library lives when nothing names another one."""
    return config_dir() / "library.json"


def resolve_library_path(explicit: str | None = None) -> Path:
    """The library to use: an explicit path, else ``$DPLANNER_LIBRARY``, else the default."""
    named = explicit or os.environ.get(LIBRARY_ENV, "")
    return Path(named).expanduser() if named else default_library_path()


def read_library_file(path: Path, *, strict: bool = False) -> list[LibraryEntry]:
    """The library's rows, in order. Tolerant of bad rows: a checkout that is not a path
    is dropped and the row kept.

    ``strict`` raises on a file that cannot be read at all instead of answering "no
    projects" — for a reader that would otherwise take a torn write for every project
    having left the library.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        if strict:
            raise
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("projects", [])
    if not isinstance(rows, list):
        return []
    entries: list[LibraryEntry] = []
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("path"), str) and row["path"]):
            continue
        checkout = row.get("checkout")
        entries.append(
            LibraryEntry(
                Path(row["path"]).expanduser(),
                Path(checkout).expanduser() if isinstance(checkout, str) and checkout else None,
            )
        )
    return entries


def write_library_file(path: Path, entries: Sequence[LibraryEntry | Path]) -> None:
    """Write the rows. A bare path is a row with no checkout — what most callers have."""
    rows: list[dict[str, str]] = []
    for entry in entries:
        if isinstance(entry, Path):
            entry = LibraryEntry(entry)
        row = {"path": str(entry.path)}
        if entry.checkout is not None:
            row["checkout"] = str(entry.checkout)
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": LIBRARY_FORMAT, "projects": rows}
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
