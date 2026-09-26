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
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from dplanner.cli.command import CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.core.clock import Clock
from dplanner.core.module_data import ModuleDataFormat, migrate_module_data
from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    main_checkout,
    origin_url,
)
from dplanner.core.storage.pointer import POINTER_FILE, resolve_index
from dplanner.domain.library_file import LIBRARY_ENV, resolve_library_path
from dplanner.domain.locations import CODE, Location, of_role
from dplanner.domain.model import Library, Project
from dplanner.domain.shelf import migrate_shelved
from dplanner.domain.store import PROJECT_META, LibraryStore, StaleWorkspaceError

# Names the current project for every verb in a shell — what Run Agent's wrapper sets, so
# an agent's calls are scoped without the briefing saying `--project` on each line.
PROJECT_ENV = "DPLANNER_PROJECT"


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

    1. ``--project`` names one, by id, folder name, or part of its title — or
       ``$DPLANNER_PROJECT`` does, which Run Agent's wrapper sets in the agent's shell.
    2. **Upwards from the working directory** for a ``project.dproj``, or for the
       ``.dplanner`` index a plan repository keeps at its root — one project directory
       per line, relative to the file. That walk is what lets a person in the plan
       repository need no configuration. **Inside an agent's worktree of a code
       repository that still carries its plan** the walk finds the branch's copy, and the
       answer is the library project with the same id — the plan of record, the one the
       window shows — never the copy. A directory found this way that is no library
       project, and no such copy, is refused rather than half-served; an index naming
       several library projects asks for ``--project``.
    3. **The working directory's repository is one a library project plans**: its
       ``origin`` is one of the project's code locations, spelt however git spells it —
       or, for a repository with no origin, it is the checkout recorded for it. An agent
       in the code checkout, or in a worktree of it, therefore needs no configuration at
       all; and the first call from a checkout the library did not know **records it**,
       so the window's Run Agent finds the code too. Several projects planning one
       repository is a refusal naming them.
    4. Failing that, every library project whose *plan* repository contains the working
       directory — a linked worktree counting as its main checkout — which is the older
       shape, a plan kept beside its code: exactly one is the answer, several a refusal,
       none means there is no current project, and verbs that need one say so.
    """
    explicit = explicit or os.environ.get(PROJECT_ENV, "")
    if explicit:
        return find_project(library, explicit)
    start = (start or Path.cwd()).resolve()
    found = _walk_up(start)
    if found:
        return _among(library, store, found)
    root = find_repo_root(start)
    if root is None:
        return None
    main = main_checkout(root).resolve()
    planned = _planning(library, store, main)
    if len(planned) == 1:
        project, location = planned[0]
        if store.checkout_for(location.repository) is None:
            store.set_checkout(location.repository, main)
        return project
    if planned:
        raise CliError(
            "this code repository is planned by several library projects — pass --project: "
            + _names([project for project, _location in planned])
        )
    matches = [
        project
        for project in library.projects
        if (directory := _dir_of(store, project)) is not None
        and (project_root := find_repo_root(directory)) is not None
        and main_checkout(project_root).resolve() == main
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise CliError(
            f"this repository holds several library projects — pass --project: {_names(matches)}"
        )
    return None


def _planning(library: Library, store: LibraryStore, main: Path) -> list[tuple[Project, Location]]:
    """The library projects one of whose code locations is the repository checked out at
    ``main``, with that location: by its origin, by the checkout recorded for the
    repository, or — for a code repository with no remote, stored as its path — by that
    path. A project naming the repository twice counts once."""
    origin = canonical_remote(origin_url(main))
    found: list[tuple[Project, Location]] = []
    for project in library.projects:
        for location in of_role(project.locations, CODE.id):
            code = location.canonical
            checkout = store.checkout_for(code)
            if (
                (origin and code == origin)
                or (checkout is not None and checkout.expanduser().resolve() == main)
                or (Path(code).is_absolute() and Path(code) == main)
            ):
                found.append((project, location))
                break
    return found


def _among(library: Library, store: LibraryStore, candidates: list[Path]) -> Project:
    """The library project among the directories the walk found — by directory, or by
    the id its ``project.dproj`` declares (a branch's copy of the plan)."""
    ids = {_project_id_at(candidate) for candidate in candidates} - {""}
    mine = [
        project
        for project in library.projects
        if _dir_of(store, project) in candidates or project.id in ids
    ]
    if len(mine) == 1:
        return mine[0]
    if mine:
        raise CliError(
            "this plan repository holds several library projects — pass --project: " + _names(mine)
        )
    first = candidates[0]
    if first in {entry.expanduser().resolve() for entry in store.archived()}:
        raise CliError(
            f"{first} is a DPlanner project you archived — run: dplanner library restore {first}"
        )
    raise CliError(
        f"{first} is a DPlanner project, but it is not in your library — "
        f"run: dplanner library add {first}"
    )


def _names(projects: Sequence[Project]) -> str:
    return ", ".join(sorted(project.title or project.folder_name for project in projects))


def _project_id_at(directory: Path) -> str:
    """The id ``project.dproj`` in ``directory`` declares, or "" when it cannot be read —
    a torn or hand-broken file is no reason to fail a lookup that has other answers."""
    try:
        raw = json.loads((directory / PROJECT_META).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(raw.get("id", "")) if isinstance(raw, dict) else ""


def _dir_of(store: LibraryStore, project: Project) -> Path | None:
    try:
        return store.project_dir(project.id).resolve()
    except KeyError:
        return None


def _walk_up(start: Path) -> list[Path]:
    """The project directories the nearest level of the walk names: the directory itself
    when it holds a ``project.dproj``, else what its index lists, else the next level up."""
    for directory in [start, *start.parents]:
        # A real project wins over an index beside it.
        if (directory / PROJECT_META).is_file():
            return [directory.resolve()]
        found = _index_candidates(directory)
        if found:
            return found
    return []


def _index_candidates(directory: Path) -> list[Path]:
    """The project directories the ``.dplanner`` index here leads to; [] when there is no
    index, or an empty one.

    A line that leads nowhere is skipped while another resolves — a project somebody
    deleted by hand must not hide its neighbours. An index none of whose lines leads
    anywhere raises rather than letting the walk continue past it: silently acting on
    some project further up when the user explicitly named this one is the failure they
    cannot see.
    """
    if not (directory / POINTER_FILE).is_file():
        return []
    entries = resolve_index(directory)
    live = [target for _line, target in entries if (target / PROJECT_META).is_file()]
    if live or not entries:
        return live
    raise CliError(
        f"{directory / POINTER_FILE} points at {entries[0][1]}, "
        f"but there is no {PROJECT_META} there"
    )


@contextmanager
def open_library(
    path: Path,
    formats: Sequence[ModuleDataFormat],
    out: TextIO,
    *,
    as_json: bool = False,
    clock: Clock | None = None,
) -> Iterator[CliContext]:
    """Open the library, hand it to a verb, and write back exactly what changed.

    Nothing is written if the verb raises: a run that failed halfway is worse than a run that
    did nothing, and version control cannot tell the difference after the fact.
    """
    store = LibraryStore(path)
    library = store.load()

    context = CliContext(
        out=out,
        as_json=as_json,
        opened=library,
        opened_store=store,
        clock=clock or Clock(),
    )
    store.dirty.connect(lambda owner_id, aspect: context.marks.add((owner_id, aspect)))
    migrate_module_data(store, formats, library)
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
