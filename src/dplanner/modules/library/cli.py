"""``dplanner library …`` — membership, headless.

The same rules as the window's New Project and Open Project: a project directory must
carry a ``project.dproj`` and sit inside a git repository. Non-interactive, so where the
window offers to ``git init``, this refuses and says what to run.

A **plan repository** — a git repository whose ``.dplanner`` index lists its projects,
several of them for several people — is joined in two commands: clone it, then
``library add <root>`` adds every project it lists; ``library browse <root>`` shows them
first, with who worked on each and when, as the Open Project wizard's browse page does.
A project somebody sent a link to is ``project open`` — the same document the window's
*Share Project…* writes, read by the same domain reader.

``library archive`` is ``library remove`` that remembers: the directory moves to the
library file's archive, is no longer loaded, and ``library restore`` — which is
``library add`` of that directory, since attaching takes it off the list — brings it back.
``library remove`` forgets an archived entry too, when no project in the library matches.
"""

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, project_arg
from dplanner.core.storage.locations import activity, find_repo_root
from dplanner.core.storage.provider import StorageError
from dplanner.domain.plan_repo import ago, list_projects, summary
from dplanner.domain.store import PROJECT_META, LibraryStore
from dplanner.modules.library.membership import LIBRARY_ORIGIN


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("library", "list"),
            summary="Every project in the library — path, title, and whether it opened.",
            run=_list,
            examples=("dplanner library list --json",),
        ),
        CliCommand(
            path=("library", "add"),
            summary="Add a project directory to the library — or every project a plan "
            "repository lists, given its root.",
            configure=_configure_add,
            run=_add,
            examples=(
                "dplanner library add ~/plans/search",
                "dplanner library add ~/plans",
            ),
        ),
        CliCommand(
            path=("library", "browse"),
            summary="The projects a plan repository holds, with who worked on each and "
            "when, and which are in this library already.",
            configure=_configure_browse,
            run=_browse,
            examples=("dplanner library browse ~/plans", "dplanner library browse ~/plans --json"),
        ),
        CliCommand(
            path=("library", "remove"),
            summary="Remove a project from the library, or from its archive. Its files stay "
            "on disk.",
            configure=project_arg,
            run=_remove,
        ),
        CliCommand(
            path=("library", "archive"),
            summary="Take a project out of the library and keep it in the archive — not "
            "loaded, until `library restore` brings it back.",
            configure=project_arg,
            run=_archive,
            examples=("dplanner library archive search",),
        ),
        CliCommand(
            path=("library", "restore"),
            summary="Bring an archived project back into the library.",
            configure=_configure_restore,
            run=_restore,
            examples=("dplanner library restore search",),
        ),
        CliCommand(
            path=("library", "path"),
            summary="Print the library file this invocation is using.",
            run=_path,
        ),
    ]


def _configure_add(parser: ArgumentParser) -> None:
    parser.add_argument(
        "directory", help="a project directory holding a project.dproj, or a plan repository"
    )


def _configure_browse(parser: ArgumentParser) -> None:
    parser.add_argument("directory", help="a plan repository: its root, or any folder inside it")


def _configure_restore(parser: ArgumentParser) -> None:
    parser.add_argument(
        "archived", help="an archived project's path, folder name, or part of its title"
    )


def _list(context: CliContext, _args: Namespace) -> int:
    library, store = context.library, context.store
    rows = [
        {
            "id": project.id,
            "title": project.title,
            "path": str(store.project_dir(project.id)),
            "available": True,
        }
        for project in library.projects
    ] + [
        {"path": str(problem.path), "available": False, "reason": problem.reason}
        for problem in store.problems()
    ]
    lines = [
        f"{row['title'] or row['path']}  ({row['path']})"
        if row["available"]
        else f"{row['path']}  — unavailable: {row['reason']}"
        for row in rows
    ]
    archived = []
    for directory in store.archived():
        found = summary(directory)
        archived.append(
            {
                "path": str(directory),
                "title": found.title,
                "steps": found.steps,
                "present": found.present,
            }
        )
    if archived:
        lines += ["", "Archived:"] + [
            f"  {row['title']}  ({row['path']})"
            if row["present"]
            else f"  {row['path']}  — the folder is gone"
            for row in archived
        ]
    context.report(
        {"projects": rows, "archived": archived},
        "\n".join(lines) if lines else "The library is empty.",
    )
    return 0


def _add(context: CliContext, args: Namespace) -> int:
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise CliError(f"no such directory: {directory}")
    if (directory / PROJECT_META).is_file():
        return _add_one(context, directory)
    return _add_all(context, directory)


def _add_one(context: CliContext, directory: Path, done: str = "added to the library") -> int:
    if find_repo_root(directory) is None:
        raise CliError(
            f"{directory} is not inside a git repository — DPlanner projects live in "
            "version control; run git init there first"
        )
    store = context.store
    for project in context.library.projects:
        if store.project_dir(project.id).resolve() == directory:
            raise CliError(f"{directory} is already in the library")
    try:
        project = store.attach(directory)
    except StorageError as error:
        raise CliError(str(error)) from error
    context.library.add_child(context.library.id, project, origin=LIBRARY_ORIGIN)
    context.report(
        {"id": project.id, "title": project.title, "path": str(directory)},
        f"“{project.title or project.folder_name}” {done}",
    )
    return 0


def _add_all(context: CliContext, root: Path) -> int:
    """A plan repository: every project it lists — or, with no index, holds — that is not
    here already, by directory or by id (the same plan in another clone)."""
    if find_repo_root(root) is None:
        raise CliError(
            f"no {PROJECT_META} in {root}, and it is not inside a git repository — "
            "not a DPlanner project, nor a plan repository"
        )
    listing = list_projects(root)
    if not listing.projects:
        raise CliError(
            f"{root} is not a DPlanner project — no {PROJECT_META} there — and no plan "
            "repository: nothing listed in its .dplanner, and no project found inside it"
        )
    store, library = context.store, context.library
    known_dirs = {store.project_dir(project.id).resolve() for project in library.projects}
    known_ids = {project.id for project in library.projects}
    # Every project a repository lists is not a request to undo somebody's archiving:
    # `library restore` is, and a named `library add` of the one directory.
    archived = {entry.expanduser().resolve() for entry in store.archived()}
    added: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for found in listing.projects:
        row = {"path": str(found.directory), "title": found.title}
        if found.directory.resolve() in known_dirs or found.project_id in known_ids:
            skipped.append(row | {"reason": "already in the library"})
            continue
        if found.directory.resolve() in archived:
            skipped.append(row | {"reason": "archived — library restore brings it back"})
            continue
        try:
            project = store.attach(found.directory)
        except StorageError as error:
            skipped.append(row | {"reason": str(error)})
            continue
        library.add_child(library.id, project, origin=LIBRARY_ORIGIN)
        known_ids.add(project.id)
        added.append(row | {"id": project.id})
    count = len(added)
    lines = [f"Added {count} project{'s' if count != 1 else ''} from {root}"]
    lines += [f"  + {row['title']}" for row in added]
    lines += [f"  = {row['title']} — {row['reason']}" for row in skipped]
    lines += [f"  ! {line} — listed in .dplanner, but leads nowhere" for line in listing.dangling]
    context.report(
        {"added": added, "skipped": skipped, "dangling": list(listing.dangling)},
        "\n".join(lines),
    )
    return 0


def _browse(context: CliContext, args: Namespace) -> int:
    start = Path(args.directory).expanduser().resolve()
    root = find_repo_root(start)
    if root is None:
        raise CliError(f"{start} is not inside a git repository")
    listing = list_projects(root)
    store, library = context.store, context.library
    known_dirs = {store.project_dir(project.id).resolve() for project in library.projects}
    known_ids = {project.id for project in library.projects}
    rows: list[dict[str, Any]] = []
    for found in listing.projects:
        seen = activity(root, "" if found.relative == "." else found.relative)
        rows.append(
            {
                "path": str(found.directory),
                "relative": found.relative,
                "id": found.project_id,
                "title": found.title,
                "steps": found.steps,
                "indexed": found.indexed,
                "in_library": found.directory.resolve() in known_dirs
                or found.project_id in known_ids,
                "last_author": seen.last_author,
                "last_when": seen.last_when,
                "authors": list(seen.authors),
                "commits": seen.commits,
            }
        )
    lines: list[str] = []
    for row in rows:
        when = (
            f"{row['last_author']}, {ago(row['last_when'])}"
            if row["last_when"]
            else "no commits yet"
        )
        who = ", ".join(row["authors"])
        line = f"{row['title']}  {row['steps']} steps  {when}"
        if who:
            line += f"  ·  {who}"
        if row["in_library"]:
            line += "  [in library]"
        lines.append(line)
    lines += [f"{line}  — listed in .dplanner, but leads nowhere" for line in listing.dangling]
    context.report(
        {"root": str(root), "projects": rows, "dangling": list(listing.dangling)},
        "\n".join(lines) or f"No projects in {root}.",
    )
    return 0


def _remove(context: CliContext, args: Namespace) -> int:
    """A library project by preference; failing that, an archived one — the archive is
    the library's too, so forgetting an entry there is the same verb."""
    try:
        project = find_project(context.library, args.project)
    except CliError as missing:
        try:
            directory = _find_archived(context.store, args.project)
        except CliError:
            raise missing from None
        context.store.forget_archived(directory)
        title = summary(directory).title
        context.report(
            {"path": str(directory), "title": title, "archived": True},
            f"“{title}” removed from the library's archive; its files stay on disk",
        )
        return 0
    # The store lets go first, then the model — the order the window's Remove keeps.
    context.store.detach(project.id)
    context.library.remove_child(project.id, origin=LIBRARY_ORIGIN)
    context.report(
        {"id": project.id, "title": project.title},
        f"“{project.title or project.folder_name}” removed from the library; "
        "its files stay on disk",
    )
    return 0


def _archive(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    directory = context.store.archive(project.id)
    context.library.remove_child(project.id, origin=LIBRARY_ORIGIN)
    context.report(
        {"id": project.id, "title": project.title, "path": str(directory)},
        f"“{project.title or project.folder_name}” archived — "
        f"dplanner library restore {directory} brings it back",
    )
    return 0


def _restore(context: CliContext, args: Namespace) -> int:
    """Restoring is adding: the store's attach takes the directory off the archive."""
    directory = _find_archived(context.store, args.archived)
    if not summary(directory).present:
        raise CliError(
            f"{directory} no longer holds a project — "
            f"dplanner library remove {directory} takes it off the archive"
        )
    return _add_one(context, directory.expanduser().resolve(), done="restored to the library")


def _find_archived(store: LibraryStore, needle: str) -> Path:
    """An archived directory by its path, its folder name, or a unique part of its title —
    the words ``library list`` printed for it."""
    archived = store.archived()
    given = Path(needle).expanduser().resolve()
    exact = [entry for entry in archived if needle == entry.name or entry.resolve() == given]
    if exact:
        return exact[0]
    lowered = needle.lower()
    partial = [entry for entry in archived if lowered in summary(entry).title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise CliError(f"no archived project matching {needle!r}")
    paths = ", ".join(sorted(str(entry) for entry in partial))
    raise CliError(f"{needle!r} matches several archived projects — use a path: {paths}")


def _path(context: CliContext, _args: Namespace) -> int:
    path = str(context.store.library_path)
    context.report({"path": path}, path)
    return 0
