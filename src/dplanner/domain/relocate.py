"""Moving a plan into a plan repository — out of the code it was born in, or on from the
plan repository it landed in the first time.

One function, :func:`move_project`, and both surfaces call it: ``dplanner project move``
and the window's Move Plan wizard. The window pauses autosave around it and rebuilds
afterwards — the store's records moved under the model — and the CLI reports the result
while its transaction flushes what the move marked.

What moves is the plan, ``PLAN_ENTRIES``: ``project.dproj``, ``modules/`` and ``steps/``,
module file areas included, so specs, images and attachments travel. What is written into
the moved ``project.dproj`` is the one fact the plan needs from then on — the code
repository it came out of, as git names it. What stays behind, on purpose: the plan's
history, which was the code's history (the target starts at *Add «title»*), and the
worktrees under the code checkout, which are code. Both repositories are committed, scoped
to exactly what changed in each; a commit that cannot be made — no git identity, say — is
reported in :attr:`Moved.notes` rather than failing a move whose files are already where
they should be.
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dplanner.core.fsio import write_atomic
from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    init_repo,
    main_checkout,
    origin_url,
    remote_label,
    repo_storage,
)
from dplanner.core.storage.pointer import POINTER_FILE, add_to_index, remove_from_index
from dplanner.core.storage.provider import StorageError, VersionedStorage
from dplanner.domain.locations import CODE, Location, primary_code, write_locations
from dplanner.domain.model import ProjectId
from dplanner.domain.store import PLAN_ENTRIES, PROJECT_META, LibraryStore

# The origin the move's two field changes carry: no view made them, so every view repaints —
# the same discipline as the store's OUTSIDE_ORIGIN for a change read off disk.
RELOCATE_ORIGIN: object = object()


class RelocateError(RuntimeError):
    """The move cannot be made as asked. The message is for the user, as it is."""


@dataclass(frozen=True)
class Moved:
    source: Path
    target: Path
    source_committed: bool
    target_committed: bool
    notes: tuple[str, ...]  # What could not be done around a move that was made.


def target_in(root: Path, folder_name: str) -> Path:
    """Where a plan lands in a plan repository: a folder at its root, by default."""
    return root / folder_name


def move_project(
    store: LibraryStore, project_id: ProjectId, target_dir: Path, *, init_repo: bool = False
) -> Moved:
    """Move one project's plan to ``target_dir``, inside a plan repository.

    Refused — nothing touched — when the target exists, when its parent is in no
    repository (``init_repo`` makes one), when the project has edits not yet on disk, or
    when the target repository is the project's code repository: the move exists to end
    that, so it is the one place colocation is refused rather than warned about.
    """
    library = store.library
    if library is None or not library.has(project_id):
        raise RelocateError("no such project in this library")
    project = library.project(project_id)
    source = store.project_dir(project_id)
    target = target_dir.expanduser()
    if target.exists():
        raise RelocateError(f"{target} already exists")
    source_root = find_repo_root(source)
    if source_root is None:
        raise RelocateError(f"{source} is not inside a git repository")
    target_root = _target_root(target, init_repo)
    if store.has_unflushed(project_id):
        raise RelocateError(
            "the project has unsaved edits in this window — let them reach disk, then try again"
        )
    primary = primary_code(project.locations)
    code = (primary.repository if primary is not None else origin_url(source)) or str(
        main_checkout(source_root)
    )
    # The moved plan names the code it came out of as its first code row; a table that
    # already has one is left exactly as it stands.
    locations = (
        project.locations
        if primary is not None
        else (Location("l1", CODE.id, code), *project.locations)
    )
    recorded = store.checkout_for(code)
    # A plan leaving the repository that also held its code leaves *from* the checkout, so
    # that is where the code is from now on. A plan already apart from its code leaves a
    # repository that is not the code's, and inherits nothing: it keeps what was recorded,
    # or stays uncheckedout here.
    checkout = recorded or (
        main_checkout(source_root) if _is_code_repository(source_root, code, recorded) else None
    )
    if _is_code_repository(target_root, code, checkout):
        raise RelocateError(
            f"{target_root} is the code repository — the plan would still live inside the "
            "code it plans; pick a plan repository"
        )

    target.mkdir(parents=True)
    for name in PLAN_ENTRIES:
        item = source / name
        if item.is_dir():
            shutil.copytree(item, target / name)
        elif item.is_file():
            shutil.copy2(item, target / name)
    meta = json.loads((target / PROJECT_META).read_text(encoding="utf-8"))
    meta["locations"] = write_locations(locations)
    meta.pop("colocation", None)
    write_atomic(
        target / PROJECT_META,
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    add_to_index(target)
    remove_from_index(source)
    shutil.rmtree(source)

    # The store follows the files, the model follows the file that was written, and the
    # library file is on disk before any rebuild reads it.
    store.relocate(project_id, target)
    if checkout is not None and recorded is None:
        store.set_checkout(code, checkout)
    library.set_field(project_id, "locations", locations, RELOCATE_ORIGIN)
    library.set_field(project_id, "colocation", "", RELOCATE_ORIGIN)
    store.flush({(library.id, "structure"), (project_id, "meta")})

    notes: list[str] = []
    title = project.title or project.folder_name
    label = remote_label(origin_url(target_root)) or target_root.name
    source_committed = _commit(
        source_root,
        [_relative(source, source_root), POINTER_FILE],
        f"Move the plan of «{title}» to {label}",
        notes,
    )
    target_committed = _commit(
        target_root, [_relative(target, target_root), POINTER_FILE], f"Add «{title}»", notes
    )
    return Moved(source, target, source_committed, target_committed, tuple(notes))


def _target_root(target: Path, init: bool) -> Path:
    parent = target.parent
    root = find_repo_root(parent)
    if root is not None:
        return root
    if not init:
        raise RelocateError(
            f"{parent} is not inside a git repository — pass --init-repo, "
            "or run git init there first"
        )
    return init_repo(parent)


def _is_code_repository(target_root: Path, code: str, checkout: Path | None) -> bool:
    canonical = canonical_remote(code)
    target_remote = canonical_remote(origin_url(target_root))
    if target_remote and target_remote == canonical:
        return True
    target_main = main_checkout(target_root).resolve()
    if checkout is not None and checkout.expanduser().resolve() == target_main:
        return True
    return Path(canonical).is_absolute() and Path(canonical) == target_main


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def _commit(root: Path, scopes: list[str], message: str, notes: list[str]) -> bool:
    storage = repo_storage(root, scopes)
    if not isinstance(storage, VersionedStorage):
        return False
    try:
        return storage.commit(message)
    except StorageError as error:
        notes.append(f"{root.name}: {error}")
        return False
