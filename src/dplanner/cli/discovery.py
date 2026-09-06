"""Finding the library, resolving the current project, opening and putting back.

Every mutating verb needs the same four things around it, and each one is a bug if a verb
has to remember it: run the pending module-data migrations, collect what got dirty, write it
once, and close. So no verb does any of them — this module wraps them all in one context
manager, and ``main.py`` is the only caller.

The migration step is the one that is easy to miss. ``migrate_module_data`` is called in
exactly one other place, ``AppBuilder.build()``. A CLI that skipped it would let a module's
writer stamp the current format onto one node while its siblings stayed at an older one, and
the next GUI open would migrate the untouched ones and leave the stamped one alone — data
loss that shows up months later, in a project nobody can reconstruct.
"""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from dplanner.cli.command import CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.core.module_data import ModuleDataFormat, migrate_module_data
from dplanner.core.storage.locations import find_repo_root, main_checkout
from dplanner.core.storage.pointer import POINTER_FILE, resolve_index
from dplanner.domain.library_file import LIBRARY_ENV, resolve_library_path
from dplanner.domain.model import Library, Project
from dplanner.domain.shelf import migrate_shelved
from dplanner.domain.store import PROJECT_META, LibraryStore, StaleWorkspaceError


def find_library(explicit: str | None = None) -> Path:
    """The library to open: ``--library``, then ``$DPLANNER_LIBRARY``, then the default.

    There is deliberately no walking or guessing here — the library is per-user state with
    one well-known home, and the *project* is what the working directory resolves (see
    :func:`find_current_project`).
    """
    path = resolve_library_path(explicit)
    if not path.is_file():
        raise CliError(
            f"no project library at {path} — open DPlanner once to create it, "
            f"or pass --library PATH (or set {LIBRARY_ENV})"
        )
    return path


def find_current_project(
    library: Library,
    store: LibraryStore,
    explicit: str | None = None,
    start: Path | None = None,
) -> Project | None:
    """The project this invocation is about, or None when nowhere says.

    In the order a person would expect — and this docstring is the contract:

    1. ``--project`` names one, by id, folder name, or part of its title.
    2. **Upwards from the working directory** for a ``project.dproj`` — or a ``.dplanner``
       pointer file whose one line is the project directory's path, relative to the
       pointer's own directory. That walk is the whole point: an agent is already sitting
       in the project's checkout, so the CLI needs no configuration at all. **Inside an
       agent's worktree the walk finds the branch's copy of the plan**, and the answer is
       the library project with the same id — the plan of record, the one the window
       shows — never the copy: a status written into a branch's copy reaches nobody until
       the branch merges. A directory found this way that is *not* in the library, and
       is not such a copy, is refused rather than half-served.
    3. Failing that, every library project whose repository contains the working
       directory — a linked worktree counting as its main checkout: exactly one is the
       answer, several is a refusal naming them, none means there is no current project —
       verbs that need one say so.
    """
    if explicit:
        return find_project(library, explicit)
    start = (start or Path.cwd()).resolve()
    found = _walk_up(start)
    if found is not None:
        for project in library.projects:
            if _dir_of(store, project) == found:
                return project
        same = _project_id_at(found)
        for project in library.projects:
            if project.id == same:
                return project
        raise CliError(
            f"{found} is a DPlanner project, but it is not in your library — "
            f"run: dplanner library add {found}"
        )
    root = find_repo_root(start)
    if root is None:
        return None
    root = main_checkout(root)
    matches = [
        project
        for project in library.projects
        if (directory := _dir_of(store, project)) is not None
        and (project_root := find_repo_root(directory)) is not None
        and main_checkout(project_root) == root
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = ", ".join(sorted(project.title or project.folder_name for project in matches))
        raise CliError(f"this repository holds several library projects — pass --project: {names}")
    return None


def _project_id_at(directory: Path) -> str:
    """The id ``project.dproj`` in ``directory`` declares, or "" when it cannot be read —
    a torn or hand-broken file is no reason to fail a lookup that has other answers."""
    try:
        raw = json.loads((directory / PROJECT_META).read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return str(raw.get("id", "")) if isinstance(raw, dict) else ""


def _dir_of(store: LibraryStore, project: Project) -> Path | None:
    try:
        return store.project_dir(project.id).resolve()
    except KeyError:
        return None


def _walk_up(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        # A real project wins over a pointer beside it.
        if (directory / PROJECT_META).is_file():
            return directory.resolve()
        pointed = _follow_pointer(directory)
        if pointed is not None:
            return pointed
    return None


def _follow_pointer(directory: Path) -> Path | None:
    """The project the ``.dplanner`` index here names, or None when there is no index.

    An index may list several projects, one per line; the first that leads to a
    ``project.dproj`` answers. An index none of whose lines leads anywhere raises rather
    than letting the walk continue past it: silently acting on some project further up
    when the user explicitly named this one is the failure they cannot see.
    """
    pointer = directory / POINTER_FILE
    if not pointer.is_file():
        return None
    entries = resolve_index(directory)
    for _line, target in entries:
        if (target / PROJECT_META).is_file():
            return target
    if not entries:
        return None
    raise CliError(f"{pointer} points at {entries[0][1]}, but there is no {PROJECT_META} there")


@contextmanager
def open_library(
    path: Path,
    formats: Sequence[ModuleDataFormat],
    out: TextIO,
    *,
    as_json: bool = False,
) -> Iterator[CliContext]:
    """Open the library, hand it to a verb, and write back exactly what changed.

    Nothing is written if the verb raises: a run that failed halfway is worse than a run that
    did nothing, and version control cannot tell the difference after the fact.
    """
    store = LibraryStore(path)
    library = store.load()

    context = CliContext(out=out, as_json=as_json, opened=library, opened_store=store)
    store.dirty.connect(lambda owner_id, aspect: context.marks.add((owner_id, aspect)))
    migrate_module_data(store, formats)
    migrate_shelved(store, formats)
    try:
        yield context
        try:
            store.flush(context.marks)
        except StaleWorkspaceError as error:
            # Somebody else wrote to the same folder while the verb ran — another CLI run,
            # or a window that autosaved. Refusing is what makes a second lock unnecessary:
            # the loser is told, nothing is overwritten, and running again picks up the
            # change.
            raise CliError(f"{error} — nothing was written; run this again") from error
    finally:
        store.close()
