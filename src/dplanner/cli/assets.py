"""The CLI's asset home: the per-aspect attach pair, and the cross-feature reports.

The operations live in :mod:`dplanner.domain.assets`; this is their CLI rendering, written
once so the argument shape, the error messages and the ``--json`` keys cannot drift between
aspects. A module gets the ``<noun> attach`` / ``<noun> assets`` pair by calling
:func:`step_asset_commands` from its Qt-free ``cli.py`` with its own wording.

The ``asset`` noun's reports — ``list``, ``uses``, ``prune`` — are cross-feature verbs in
the ``project lint`` mould: this file owns the shapes and the ``--json`` keys, each owning
module exports an ``asset_source()`` from its Qt-free half, and the composition root
assembles the tuple. Nothing here imports a module. The verbs that *write* what the
asset-browser module itself stores (``asset attach``, ``asset name``) live in that
module's ``cli.py``, the ``scope`` split: the derivation's home holds the reports, the
owner keeps its writes.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.assets import (
    AssetEntry,
    AssetSource,
    assets,
    attach,
    catalog,
    prunable,
)
from dplanner.domain.model import Library, Project

# The display titles beside a project — the browser module's data, injected by the
# composition root so this file needs no module import.
Titles = Callable[[Project], Mapping[str, str]]


def step_asset_commands(
    noun: str,
    module_id: str,
    *,
    file_help: str,
    attach_summary: str,
    assets_summary: str,
    example_step: str,
    attached_text: Callable[[str], str] = lambda name: name,
) -> list[CliCommand]:
    """The two commands, worded by the calling module.

    ``attached_text`` renders the human line after an attach — the description aspect uses
    it to say how to reference the image from markdown.
    """

    def configure_attach(parser: ArgumentParser) -> None:
        step_arg(parser)
        parser.add_argument("file", help=file_help)

    def run_attach(context: CliContext, args: Namespace) -> int:
        source = Path(args.file)
        if not source.is_file():
            raise CliError(f"no such file: {args.file}")
        step = find_step(context.library, args.step, context.current)
        name = attach(context.store.files(step.id, module_id), source.read_bytes(), source.name)
        context.report({"step": step.id, "asset": name}, attached_text(name))
        return 0

    def run_assets(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        names = assets(context.store.files(step.id, module_id))
        context.report({"step": step.id, "assets": names}, "\n".join(names) or "(none)")
        return 0

    return [
        CliCommand(
            path=(noun, "attach"),
            summary=attach_summary,
            configure=configure_attach,
            run=run_attach,
            examples=(f"dplanner {noun} attach {example_step} diagram.png",),
        ),
        CliCommand(
            path=(noun, "assets"),
            summary=assets_summary,
            configure=step_arg,
            run=run_assets,
            examples=(f"dplanner {noun} assets {example_step}",),
        ),
    ]


def find_asset(entries: Sequence[AssetEntry], titles: Mapping[str, str], ref: str) -> AssetEntry:
    """The entry ``ref`` means: content name, basename, a unique prefix, or a title.

    :mod:`.lookup`'s discipline — the prefix pass makes the names the reports *print*
    names the verbs also *accept*, and an ambiguous reference is refused with what to
    type next, never resolved to the first match.
    """
    named = {entry.name: entry for entry in entries}
    if ref in named:
        return named[ref]
    exact = [e for e in entries if PurePosixPath(e.name).name == ref]
    if exact:
        return exact[0]
    prefixed = [e for e in entries if ref and PurePosixPath(e.name).name.startswith(ref)]
    if len(prefixed) == 1:
        return prefixed[0]
    if prefixed:
        options = ", ".join(sorted(_label(e, titles) for e in prefixed))
        raise CliError(f"{ref!r} is the start of several asset names — type more of it: {options}")
    lowered = ref.lower()
    titled = [e for e in entries if ref and lowered in titles.get(e.name, "").lower()]
    if len(titled) == 1:
        return titled[0]
    if not titled:
        raise CliError(f"no asset matching {ref!r} — see `dplanner asset list`")
    options = ", ".join(sorted(_label(e, titles) for e in titled))
    raise CliError(f"{ref!r} matches several assets — use a content name: {options}")


def _label(entry: AssetEntry, titles: Mapping[str, str]) -> str:
    basename = PurePosixPath(entry.name).name
    title = titles.get(entry.name, "")
    return f"{basename} ({title})" if title else basename


def catalog_commands(*, sources: Sequence[AssetSource], titles: Titles) -> list[CliCommand]:
    """The cross-feature reports over the asset catalog."""

    def entries_for(context: CliContext, project: Project) -> list[AssetEntry]:
        return catalog(context.library, project, context.store.files, sources)

    def location_rows(context: CliContext, entry: AssetEntry) -> list[dict[str, Any]]:
        # Both forms of every path: the area-relative name is what markdown links, the
        # absolute path is what a consumer running elsewhere opens.
        return [
            {
                "node": location.node_id,
                "module": location.module_id,
                "source": source.label,
                "name": location.name,
                "path": str(
                    context.store.files(location.node_id, location.module_id).absolute(
                        location.name
                    )
                ),
                "uses": [
                    {
                        "kind": use.subject_kind,
                        "id": use.subject_id,
                        "title": use.subject,
                        "where": use.where,
                    }
                    for use in location.uses
                ],
            }
            for source, location in entry.locations
        ]

    def subject_of(library: Library, node_id: str) -> str:
        node = library.node(node_id)
        return getattr(node, "title", "") or node_id[:8]

    def configure_list(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument("--unused", action="store_true", help="only what nothing uses")
        parser.add_argument(
            "--source", help="only one module's areas, by id — see the module column"
        )

    def run_list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        entries = entries_for(context, project)
        if args.source:
            known = {source.id for source in sources}
            if args.source not in known:
                raise CliError(
                    f"no asset source {args.source!r} — one of {', '.join(sorted(known))}"
                )
            entries = [
                entry
                for entry in entries
                if any(source.id == args.source for source, _location in entry.locations)
            ]
        if args.unused:
            entries = [entry for entry in entries if entry.unused]
        project_titles = titles(project)
        rows = [
            {
                "name": entry.name,
                "title": project_titles.get(entry.name, ""),
                "unused": entry.unused,
                "locations": location_rows(context, entry),
            }
            for entry in entries
        ]
        if not entries:
            empty = (
                "No unused assets."
                if args.unused
                else "No assets. Paste an image into a description, or"
                " `dplanner describe attach <step> <file>`."
            )
            context.report({"project": project.id, "assets": rows}, empty)
            return 0
        width = max(len(PurePosixPath(entry.name).name) for entry in entries)
        lines = []
        for entry in entries:
            wheres = ", ".join(dict.fromkeys(use.where for use in entry.uses))
            count = len(entry.uses)
            status = f"{count} use{'s' if count != 1 else ''} — {wheres}" if count else "unused"
            title = project_titles.get(entry.name, "")
            named = f"{title!r}  " if title else ""
            lines.append(f"{PurePosixPath(entry.name).name:<{width}}  {named}{status}")
        swept = sum(entry.unused for entry in entries)
        lines.append(f"{len(entries)} assets, {swept} unused")
        context.report({"project": project.id, "assets": rows}, "\n".join(lines))
        return 0

    def configure_uses(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument(
            "ref", help="asset content name, its basename, a unique prefix, or its title"
        )

    def run_uses(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        entries = entries_for(context, project)
        project_titles = titles(project)
        entry = find_asset(entries, project_titles, args.ref)
        lines = [_label(entry, project_titles)]
        for source, location in entry.locations:
            beside = subject_of(context.library, location.node_id)
            if location.uses:
                lines += [f"  used by {use.subject} — {use.where}" for use in location.uses]
            else:
                lines.append(f"  unused copy beside {beside} ({source.label})")
        context.report(
            {
                "project": project.id,
                "asset": {
                    "name": entry.name,
                    "title": project_titles.get(entry.name, ""),
                    "unused": entry.unused,
                    "locations": location_rows(context, entry),
                },
            },
            "\n".join(lines),
        )
        return 0

    def configure_prune(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="delete the listed files; without it the run only reports",
        )

    def run_prune(context: CliContext, args: Namespace) -> int:
        """Deletes go straight through the file areas, one by one — a failure part-way
        has removed only files that were individually unused, and version control still
        holds every one of them."""
        project = find_project(context.library, args.project)
        swept = prunable(entries_for(context, project))
        rows = [
            {
                "node": location.node_id,
                "module": location.module_id,
                "name": location.name,
                "path": str(
                    context.store.files(location.node_id, location.module_id).absolute(
                        location.name
                    )
                ),
            }
            for _source, location in swept
        ]
        if not swept:
            context.report(
                {"project": project.id, "applied": bool(args.apply), "pruned": []},
                "Nothing to sweep.",
            )
            return 0
        lines = [
            f"{subject_of(context.library, location.node_id)}: {location.name} ({source.label})"
            for source, location in swept
        ]
        count = len(swept)
        if args.apply:
            for _source, location in swept:
                context.store.files(location.node_id, location.module_id).remove(location.name)
            lines.append(
                f"Removed {count} file{'s' if count != 1 else ''} — not undoable;"
                " version control still has them."
            )
        else:
            lines.append(
                f"{count} unused file{'s' if count != 1 else ''} — run again with"
                " --apply to delete."
            )
        context.report(
            {"project": project.id, "applied": bool(args.apply), "pruned": rows},
            "\n".join(lines),
        )
        return 0

    return [
        CliCommand(
            path=("asset", "list"),
            summary="Every asset the project carries — images and files beside its steps "
            "and specs — with what still uses each.",
            configure=configure_list,
            run=run_list,
            examples=(
                "dplanner asset list discovery",
                "dplanner asset list discovery --unused",
                "dplanner asset list discovery --json",
            ),
        ),
        CliCommand(
            path=("asset", "uses"),
            summary="Where one asset is used: every copy, and what references each.",
            configure=configure_uses,
            run=run_uses,
            examples=(
                "dplanner asset uses discovery ab12cd34",
                "dplanner asset uses discovery 'Login mock' --json",
            ),
        ),
        CliCommand(
            path=("asset", "prune"),
            summary="Sweep the copies nothing uses. A dry run by default; --apply "
            "deletes, which is not undoable — version control keeps the bytes.",
            configure=configure_prune,
            run=run_prune,
            examples=(
                "dplanner asset prune discovery",
                "dplanner asset prune discovery --apply",
            ),
        ),
    ]
