"""The module's Qt-free half: the pool, display titles, and their verbs.

The cross-feature reports — ``asset list``, ``asset uses``, ``asset prune`` — live in
:mod:`dplanner.cli.assets`, fed by the composition root; this file owns only what the
module itself stores. Two things, chosen by content exactly as ``spec`` chooses:

**The pool is a file area.** ``modules/project_assets/assets/`` beside the project — a
staging shelf for images nothing uses yet, so collecting screenshots and using them are
two acts. Blobs, so not undoable, and ``prunable=False``: a freshly staged image is
unused by definition, and a sweep that emptied the shelf would punish staging.

**Titles are module data.** ``{"titles": {content name: title}}`` beside the project,
written through a command and therefore undoable. Keyed by content name because identical
bytes carry one name project-wide — one title covers every copy — and because a link
never contains the title, renaming can never break one; that is the whole design.
A title whose asset is gone is tolerated dead weight, never resurrected by a rewrite.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dplanner.cli.assets import find_asset
from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, project_arg
from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.assets import (
    AssetLocation,
    AssetSource,
    area_assets,
    attach,
    catalog,
)
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor

MODULE_ID = "project_assets"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read_titles(project: Project) -> dict[str, str]:
    """Display title by content name. Unreadable entries read as absent."""
    raw = project.module_data.get(MODULE_ID, {}).get("titles")
    if not isinstance(raw, dict):
        return {}
    return {
        name: title
        for name, title in raw.items()
        if isinstance(name, str) and isinstance(title, str) and title
    }


def write_titles(titles: Mapping[str, str]) -> dict[str, Any]:
    """The entry to store. No titles gives ``{}``, which removes the file."""
    kept = {name: title for name, title in sorted(titles.items()) if title}
    if not kept:
        return {}
    return stamped({"titles": kept}, DATA_FORMAT.version)


def asset_source() -> AssetSource:
    """The pool's slice of the catalog: staged images, used by nothing, swept by nobody."""

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        return [
            AssetLocation(node_id=project.id, module_id=MODULE_ID, name=name, uses=())
            for name in area_assets(files, project.id, MODULE_ID)
        ]

    return AssetSource(id=MODULE_ID, label="Pool", scan=scan, prunable=False)


def commands(*, sources: Sequence[AssetSource]) -> list[CliCommand]:
    """The module's own verbs. ``sources`` is the same tuple the reports read, injected by
    the composition root so ``asset name`` resolves a reference against the whole catalog."""

    def configure_attach(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument("file", help="the image or file to stage in the project's pool")

    def run_attach(context: CliContext, args: Namespace) -> int:
        source = Path(args.file)
        if not source.is_file():
            raise CliError(f"no such file: {args.file}")
        project = find_project(context.library, args.project)
        area = context.store.files(project.id, MODULE_ID)
        name = attach(area, source.read_bytes(), source.name)
        context.report(
            {"project": project.id, "asset": name, "path": str(area.absolute(name))},
            f"{name}\nStaged in the pool — pick it into any editor with Insert from"
            " Assets…, and see it with `dplanner asset list`",
        )
        return 0

    def configure_name(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument(
            "ref", help="asset content name, its basename, a unique prefix, or its title"
        )
        parser.add_argument("title", nargs="?", default="", help="the display name to give it")
        parser.add_argument("--clear", action="store_true", help="drop the display name instead")

    def run_name(context: CliContext, args: Namespace) -> int:
        if args.clear == bool(args.title):
            raise CliError("give a title, or --clear to drop the one it has")
        project = find_project(context.library, args.project)
        titles = read_titles(project)
        entries = catalog(context.library, project, context.store.files, sources)
        entry = find_asset(entries, titles, args.ref)
        if args.clear:
            titles.pop(entry.name, None)
        else:
            titles[entry.name] = args.title
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_titles(titles), label="Rename Asset")
        )
        context.report(
            {"project": project.id, "asset": entry.name, "title": args.title},
            f"{entry.name} has no display name now"
            if args.clear
            else f"{entry.name} is now {args.title!r}",
        )
        return 0

    return [
        CliCommand(
            path=("asset", "attach"),
            summary="Stage an image in the project's pool, to reuse from any editor later.",
            configure=configure_attach,
            run=run_attach,
            examples=(
                "dplanner asset attach discovery login-mock.png",
                "dplanner asset attach discovery login-mock.png --json",
            ),
        ),
        CliCommand(
            path=("asset", "name"),
            summary="Give an asset a display name — shown wherever it is listed, never "
            "part of any link, so renaming cannot break a reference.",
            configure=configure_name,
            run=run_name,
            examples=(
                "dplanner asset name discovery ab12cd34 'Login mock'",
                "dplanner asset name discovery 'Login mock' --clear",
            ),
        ),
    ]
