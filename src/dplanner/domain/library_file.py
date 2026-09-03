"""The project library file: which projects a user is planning.

Per user, per machine — it lives in the Qt-free config directory (see
:mod:`dplanner.core.config_dir`) so the CLI can resolve it without a graphics stack, and it
is never shared through version control: it is a list of *this machine's* paths. The window
and the CLI read the same file, which is what makes ``dplanner`` verbs and the Projects
panel agree about what exists.

The format is deliberately small::

    {"format": 1, "projects": [{"path": "/home/anna/code/widget/planning"}]}

Paths are absolute (``~`` is allowed) and the array order is the order the panel shows.
Reading is tolerant — a malformed entry is skipped, not fatal — because this file is edited
by two instances and the occasional human, and refusing the whole library over one bad row
would take every healthy project down with it.
"""

import json
import os
from collections.abc import Sequence
from pathlib import Path

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic

LIBRARY_ENV = "DPLANNER_LIBRARY"
LIBRARY_FORMAT = 1


def default_library_path() -> Path:
    """Where the library lives when nothing names another one."""
    return config_dir() / "library.json"


def resolve_library_path(explicit: str | None = None) -> Path:
    """The library to use: an explicit path, else ``$DPLANNER_LIBRARY``, else the default."""
    named = explicit or os.environ.get(LIBRARY_ENV, "")
    return Path(named).expanduser() if named else default_library_path()


def read_library_file(path: Path, *, strict: bool = False) -> list[Path]:
    """The project directories the library lists, in order. Tolerant of bad rows.

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
    entries = raw.get("projects", [])
    if not isinstance(entries, list):
        return []
    directories: list[Path] = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"]:
            directories.append(Path(entry["path"]).expanduser())
    return directories


def write_library_file(path: Path, directories: Sequence[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format": LIBRARY_FORMAT,
        "projects": [{"path": str(directory)} for directory in directories],
    }
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
