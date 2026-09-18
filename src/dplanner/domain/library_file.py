"""The project library file: which projects a user is planning, and where this machine
has the repositories they name.

Per user, per machine — it lives in the Qt-free config directory (see
:mod:`dplanner.core.config_dir`) so the CLI can resolve it without a graphics stack, and it
is never shared through version control: it is a list of *this machine's* paths. The window
and the CLI read the same file, which is what makes ``dplanner`` verbs and the Projects
panel agree about what exists.

The format is deliberately small::

    {
        "format": 3,
        "projects": [{"path": "/home/anna/plans/search"}],
        "checkouts": {"github.com/acme/widget": "/home/anna/src/widget"},
    }

Paths are absolute (``~`` is allowed) and the array order is the order the panel shows.
``checkouts`` is where this machine has each repository a project names, keyed by the
repository's canonical spelling (:func:`~dplanner.core.storage.locations.canonical_remote`)
— a checkout is a fact about a *repository* on this machine, not about a project, so two
projects naming one repository share it and a second plan for the same code never asks for
a second clone. A format-2 row carried its project's code checkout instead; reading one
files it under the checkout's own origin. Reading is tolerant — a malformed entry is
skipped, not fatal — because this file is edited by two instances and the occasional
human, and refusing the whole library over one bad row would take every healthy project
down with it.
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic
from dplanner.core.storage.locations import canonical_remote, origin_url

LIBRARY_ENV = "DPLANNER_LIBRARY"
LIBRARY_FORMAT = 3


@dataclass
class LibraryFile:
    """What the file says: the project directories in order, and this machine's checkouts
    by canonical repository."""

    projects: list[Path] = field(default_factory=list)
    checkouts: dict[str, Path] = field(default_factory=dict)


def default_library_path() -> Path:
    """Where the library lives when nothing names another one."""
    return config_dir() / "library.json"


def resolve_library_path(explicit: str | None = None) -> Path:
    """The library to use: an explicit path, else ``$DPLANNER_LIBRARY``, else the default."""
    named = explicit or os.environ.get(LIBRARY_ENV, "")
    return Path(named).expanduser() if named else default_library_path()


def checkout_key(repository: str) -> str:
    """The map's key for a repository, spelt however git spells it."""
    return canonical_remote(repository)


def read_library_file(path: Path, *, strict: bool = False) -> LibraryFile:
    """The library's rows, in order, and its checkouts. Tolerant of bad rows: a checkout
    that is not a path is dropped and the row kept.

    ``strict`` raises on a file that cannot be read at all instead of answering "no
    projects" — for a reader that would otherwise take a torn write for every project
    having left the library.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if strict:
            raise
        return LibraryFile()
    if not isinstance(raw, dict):
        return LibraryFile()
    rows = raw.get("projects", [])
    if not isinstance(rows, list):
        return LibraryFile()
    found = LibraryFile()
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("path"), str) and row["path"]):
            continue
        found.projects.append(Path(row["path"]).expanduser())
        checkout = row.get("checkout")  # A format-2 row: the project's code checkout.
        if isinstance(checkout, str) and checkout:
            _adopt_checkout(found.checkouts, Path(checkout).expanduser())
    checkouts = raw.get("checkouts", {})
    if isinstance(checkouts, dict):
        for key, value in checkouts.items():
            if isinstance(key, str) and key and isinstance(value, str) and value:
                found.checkouts[key] = Path(value).expanduser()
    return found


def _adopt_checkout(checkouts: dict[str, Path], checkout: Path) -> None:
    """A format-2 checkout, filed under what it is a checkout of: its origin, or — for a
    repository with no remote — its own resolved path."""
    key = checkout_key(origin_url(checkout) or str(checkout))
    checkouts.setdefault(key, checkout)


def write_library_file(
    path: Path, entries: Sequence[Path], checkouts: Mapping[str, Path] | None = None
) -> None:
    """Write the rows and the checkouts. Absence encodes the default: no checkouts, no key."""
    rows = [{"path": str(entry)} for entry in entries]
    data: dict[str, object] = {"format": LIBRARY_FORMAT, "projects": rows}
    if checkouts:
        data["checkouts"] = {key: str(value) for key, value in sorted(checkouts.items())}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
