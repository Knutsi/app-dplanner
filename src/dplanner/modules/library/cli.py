"""``dplanner library …`` — membership, headless.

The same rules as File ▸ New/Open Project: a project directory must exist, carry a
``project.dproj``, and sit inside a git repository. Non-interactive, so where the GUI
offers to ``git init``, this refuses and says what to run.
"""

from argparse import ArgumentParser, Namespace
from pathlib import Path

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, project_arg
from dplanner.core.storage.locations import find_repo_root
from dplanner.core.storage.provider import StorageError
from dplanner.domain.store import PROJECT_META
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
            summary="Add an existing project directory to the library.",
            configure=_configure_add,
            run=_add,
            examples=("dplanner library add ~/code/widget/planning",),
        ),
        CliCommand(
            path=("library", "remove"),
            summary="Remove a project from the library. Its files stay on disk.",
            configure=project_arg,
            run=_remove,
        ),
        CliCommand(
            path=("library", "path"),
            summary="Print the library file this invocation is using.",
            run=_path,
        ),
    ]


def _configure_add(parser: ArgumentParser) -> None:
    parser.add_argument("directory", help="a project directory holding a project.dproj")


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
    context.report({"projects": rows}, "\n".join(lines) if lines else "The library is empty.")
    return 0


def _add(context: CliContext, args: Namespace) -> int:
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise CliError(f"no such directory: {directory}")
    if not (directory / PROJECT_META).is_file():
        raise CliError(f"no {PROJECT_META} in {directory} — not a DPlanner project")
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
        f"“{project.title or project.folder_name}” added to the library",
    )
    return 0


def _remove(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    context.library.remove_child(project.id, origin=LIBRARY_ORIGIN)
    context.store.detach(project.id)
    context.report(
        {"id": project.id, "title": project.title},
        f"“{project.title or project.folder_name}” removed from the library; "
        "its files stay on disk",
    )
    return 0


def _path(context: CliContext, _args: Namespace) -> int:
    path = str(context.store.library_path)
    context.report({"path": path}, path)
    return 0
