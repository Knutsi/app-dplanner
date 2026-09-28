"""What a plan repository holds: the projects a clone can offer to a library.

A plan repository is a git repository whose root carries the ``.dplanner`` index — one
project directory per line, in the order a panel shows them — and whose projects are
folders in it, flat at the root by default (``<repo>/<slug>/project.dproj``), nested where
somebody chose to. The index is the structure and gives the order; the repository is also
scanned, shallowly, so one made before the index existed — or whose index fell behind —
still offers every project it holds.

Two readers, one function: ``dplanner library browse`` (and ``library add <root>``) and the
Open Project wizard's browse page. Nothing here opens a project or touches the library — it
reads the one file that says what a project is called and how many steps it has, which is
also how the archive names a project it no longer opens (:func:`summary`).
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
        raw = json.loads((directory / PROJECT_META).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def list_projects(root: Path) -> PlanRepo:
    """The projects at ``root``: those the index lists, in its order, then whatever the scan
    finds that it does not.

    The index is not trusted to be complete: a Save once left it uncommitted, so a clone
    held projects its index had never heard of — and a listing that hid them hid the plans
    the person had come for.
    """
    root = root.expanduser().resolve()
    projects: list[PlanProject] = []
    dangling: list[str] = []
    for line, target in resolve_index(root):
        if (target / PROJECT_META).is_file():
            projects.append(_describe(root, target, indexed=True))
        else:
            dangling.append(line)
    listed = {project.directory for project in projects}
    projects += [
        _describe(root, directory, indexed=False)
        for directory in scan_projects(root)
        if directory.resolve() not in listed
    ]
    return PlanRepo(root, tuple(projects), tuple(dangling))


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


def plan_repositories_in(folder: Path) -> list[Path]:
    """The git repositories directly in ``folder`` that hold a plan — the ones worth
    offering before anybody has browsed to them, sorted by name.

    Cheaper than :func:`list_projects` on purpose, since it runs over every checkout a
    person keeps: a project the index lists inside the repository, or one at its root or a
    folder down. A ``.dplanner`` alone is not enough — in a code repository it points at a
    plan kept elsewhere.
    """
    try:
        children = sorted(child for child in folder.iterdir() if (child / ".git").exists())
    except OSError:
        return []
    return [child for child in children if _holds_projects(child.resolve())]


def _holds_projects(root: Path) -> bool:
    listed = any(
        target.is_relative_to(root) and (target / PROJECT_META).is_file()
        for _line, target in resolve_index(root)
    )
    try:
        return listed or bool(scan_projects(root, depth=1))
    except OSError:
        return False


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


@dataclass(frozen=True)
class ProjectSummary:
    """What a project directory says about itself, read without opening the project."""

    project_id: str
    title: str  # The folder's name when the project gives none.
    steps: int
    present: bool  # Whether the directory still holds a project.dproj at all.


def summary(directory: Path) -> ProjectSummary:
    """The project at ``directory`` as a row would name it — a browse listing's, or an
    archived project's, which is never opened."""
    meta = read_meta(directory)
    children = meta.get("children", [])
    return ProjectSummary(
        project_id=str(meta.get("id", "")),
        title=str(meta.get("title", "")) or directory.name,
        steps=len(children) if isinstance(children, list) else 0,
        present=(directory / PROJECT_META).is_file(),
    )


def _describe(root: Path, directory: Path, *, indexed: bool) -> PlanProject:
    found = summary(directory)
    return PlanProject(
        directory=directory,
        relative=Path(os.path.relpath(directory, root)).as_posix(),
        project_id=found.project_id,
        title=found.title,
        steps=found.steps,
        indexed=indexed,
    )
