"""Where a folder source points, and the walk it runs.

The walk itself is ``domain/document_folder.py``'s, shared with the Git kind. What lives
here is the locator — one absolute path — and its validation, which runs on **every read**
because a plan is shared and a colleague's ``spec.json`` is input.

**A folder source is local by design.** The locator holds a path on one machine, so a
colleague who opens the plan is told the folder is not on their computer rather than
fetching something else of the same name. That is the honest answer: the shareable version
of a folder is a Git repository, which is its own kind.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from dplanner.domain.document_folder import FolderScan, freshness
from dplanner.domain.document_folder import snapshot as walk
from dplanner.domain.document_source import Freshness, Locator, Snapshot

KIND = "folder"


def valid_locator(locator: Mapping[str, object]) -> Locator | None:
    """The locator as this kind understands it, or None — re-checked on every read."""
    path = locator.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return None
    return {"path": path}


def title_for(path: Path) -> str:
    """What the source is called when it is added: the folder's own name."""
    return path.name or str(path)


def folder_scan(locator: Locator) -> FolderScan:
    return FolderScan(root=Path(locator["path"]))


def browse_url(locator: Locator) -> str:
    """Where a person opens it: the folder itself, in whatever opens folders here."""
    return Path(locator["path"]).as_uri()


def fetch(
    locator: Locator,
    known: Mapping[str, str],
    progress: Callable[[float], None] = lambda _f: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Snapshot:
    return walk(folder_scan(locator), known, progress, cancelled)


def check(locator: Locator, known: Mapping[str, str]) -> Freshness:
    return freshness(folder_scan(locator), known)
