"""What a plan repository holds: the projects a clone can offer to a library.

A plan repository is a git repository whose root carries the ``.dplanner`` index — one
project directory per line, in the order a panel shows them — and whose projects are
folders in it, flat at the root by default (``<repo>/<slug>/project.dproj``), nested where
somebody chose to. The index is the structure; a repository made before it existed has no
index and is scanned instead, shallowly, so a clone from any era answers the same question.

Two readers, one function: ``dplanner library browse`` (and ``library add <root>``) and the
Open Projects dialog. Nothing here opens a project or touches the library — it reads the
one file that says what a project is called and how many steps it has.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dplanner.core.storage.pointer import WORKTREES_DIR, resolve_index
from dplanner.domain.store import MODULES_DIR, PROJECT_META, STEPS_DIR

# How deep a scan looks for `project.dproj` when there is no index: the root, a folder, a
# folder in a folder, a team's folder in that. Deeper is somebody else's directory.
SCAN_DEPTH = 3
# Never descended into: git's own store, a project's own subtrees (a project holds no
# projects), and the worktrees Run Agent keeps under a checkout — a branch's copy of a
# plan is not a second plan.
SKIPPED = frozenset({".git", STEPS_DIR, MODULES_DIR, WORKTREES_DIR})


@dataclass(frozen=True)
class PlanProject:
    directory: Path
    relative: str  # Posix, relative to the root; "." for a repository that is one project.
    project_id: str
    title: str
    steps: int
    indexed: bool  # Listed in the index, or found by the scan.


@dataclass(frozen=True)
class PlanRepo:
    root: Path
    projects: tuple[PlanProject, ...]
    dangling: tuple[str, ...]  # Index lines that lead to no project.


def read_meta(directory: Path) -> dict[str, Any]:
    """``project.dproj`` as a dict, or {} for one that cannot be read — a torn or
    hand-broken file is no reason to fail a listing that has other rows."""
    try:
        raw = json.loads((directory / PROJECT_META).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def list_projects(root: Path) -> PlanRepo:
    """The projects at ``root``: in index order when there is an index, else by scan."""
    root = root.expanduser().resolve()
    entries = resolve_index(root)
    if entries:
        projects: list[PlanProject] = []
        dangling: list[str] = []
        for line, target in entries:
            if (target / PROJECT_META).is_file():
                projects.append(_describe(root, target, indexed=True))
            else:
                dangling.append(line)
        return PlanRepo(root, tuple(projects), tuple(dangling))
    found = tuple(_describe(root, directory, indexed=False) for directory in scan_projects(root))
    return PlanRepo(root, found, ())


def scan_projects(root: Path, depth: int = SCAN_DEPTH) -> list[Path]:
    """Every directory holding a ``project.dproj`` within ``depth`` levels of ``root``,
    sorted by path; a project's own subtree is never entered."""
    found: list[Path] = []

    def walk(directory: Path, level: int) -> None:
        if (directory / PROJECT_META).is_file():
            found.append(directory)
            return
        if level >= depth:
            return
        for child in sorted(directory.iterdir()):
            if child.is_dir() and child.name not in SKIPPED:
                walk(child, level + 1)

    walk(root, 0)
    return found


_UNITS = (
    ("year", 365 * 86400),
    ("month", 30 * 86400),
    ("week", 7 * 86400),
    ("day", 86400),
    ("hour", 3600),
    ("minute", 60),
)


def ago(iso: str, now: datetime | None = None) -> str:
    """``2 days ago`` from an ISO-8601 stamp — how a row says when a plan last moved.
    "" for no stamp; the stamp itself when it cannot be read."""
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if now is None:
        now = datetime.now(UTC) if when.tzinfo is not None else datetime.now()
    seconds = max(0.0, (now - when).total_seconds())
    for unit, size in _UNITS:
        count = int(seconds // size)
        if count >= 1:
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def _describe(root: Path, directory: Path, *, indexed: bool) -> PlanProject:
    meta = read_meta(directory)
    children = meta.get("children", [])
    relative = Path(os.path.relpath(directory, root)).as_posix()
    return PlanProject(
        directory=directory,
        relative=relative,
        project_id=str(meta.get("id", "")),
        title=str(meta.get("title", "")) or directory.name,
        steps=len(children) if isinstance(children, list) else 0,
        indexed=indexed,
    )
