"""``dplanner report`` — the plan as a page, a site, a workbook, a table.

The terminal's half of reporting: the same ``Report`` the window renders, built here from
the sources the composition root hands over. ``html`` prints the page (or writes it with
``--out``), ``site`` lays the site out — under the plan repository's ``reports/``, or at
the project's reporting location when it names one this machine has — and never commits:
the CLI is a transaction over the plan, and a Save is the window's. ``xlsx`` and ``csv``
write the tables, ``tables`` names them.

An optional ``project`` positional falls back to the current project, the one the working
directory is in, because an agent finishing a step wants ``dplanner report site`` and not
a name it would have to look up first.
"""

import csv
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.cli.report import page, sheets, website
from dplanner.cli.report.assemble import Report, build
from dplanner.cli.report.parts import ReportSource
from dplanner.core.storage.locations import find_repo_root, origin_url
from dplanner.domain.model import Project, Step


def commands(
    *,
    sources: Sequence[ReportSource],
    key_of: Callable[[Step], str],
    kind_of: Callable[[Step], str],
    status_for: Callable[[Step], str],
    reporting_site: Callable[[CliContext, Project], website.SiteTarget | None] = (
        lambda _context, _project: None
    ),
) -> list[CliCommand]:
    """``reporting_site`` says where a project publishes instead of beside its plan — its
    reporting location, when it names one and this machine has that repository — handed in
    by the root, which alone knows the roles."""

    def build_for(context: CliContext, project: Project) -> Report:
        root = find_repo_root(context.store.project_dir(project.id))
        return build(
            context.library,
            project,
            context.store.files,
            sources,
            key_of=key_of,
            kind_of=kind_of,
            status_for=status_for,
            plan_remote=origin_url(root) if root is not None else "",
            today=context.clock.today(),
        )

    def html(context: CliContext, args: Namespace) -> int:
        project = _project(context, args)
        report = build_for(context, project)
        text = page.render(report, about=page.about_text(report))
        if not args.out:
            # The output is the artefact — `project export`'s rule: no --json wrapping.
            context.out.write(text)
            return 0
        path = Path(args.out)
        path.write_text(text, encoding="utf-8")
        context.report(
            {"project": project.id, "path": str(path), "bytes": len(text.encode("utf-8"))},
            f"{project.title}: report written to {path}",
        )
        return 0

    def site(context: CliContext, args: Namespace) -> int:
        projects = list(context.library.projects) if args.all else [_project(context, args)]
        by_target: dict[website.SiteTarget, list[tuple[Project, Path]]] = {}
        for project in projects:
            root = find_repo_root(context.store.project_dir(project.id))
            if root is None:
                raise CliError(f"{project.title!r} is not inside a git repository")
            if args.out:
                target = website.SiteTarget(Path(args.out), Path(args.out))
            else:
                target = reporting_site(context, project) or website.plan_site(root)
            by_target.setdefault(target, []).append((project, root))
        written: list[dict[str, Any]] = []
        lines: list[str] = []
        for target, members in sorted(by_target.items(), key=lambda item: str(item[0].site)):
            pages = []
            for project, root in members:
                report = build_for(context, project)
                slug = website.slug_for(context.store.project_dir(project.id), root)
                pages.append(
                    website.SiteReport(
                        slug,
                        page.render(report, about=page.about_text(report)),
                        page.summary_script(report, slug),
                    )
                )
            website.write(target, pages)
            written.append(
                {
                    "root": str(target.repo_root),
                    "site": str(target.site),
                    "projects": [p.slug for p in pages],
                }
            )
            lines.append(f"{target.site}/")
            lines += [f"  {p.slug}/{website.INDEX_NAME}" for p in pages]
            lines.append(f"  {website.INDEX_NAME}")
        context.report({"sites": written}, "\n".join(lines))
        return 0

    def xlsx(context: CliContext, args: Namespace) -> int:
        project = _project(context, args)
        report = build_for(context, project)
        path = Path(args.out)
        sheets.write_workbook(path, report)
        names = [table.title for table in report.tables()]
        context.report(
            {"project": project.id, "path": str(path), "sheets": names},
            f"{project.title}: {len(names)} sheets written to {path}",
        )
        return 0

    def csv_out(context: CliContext, args: Namespace) -> int:
        project = _project(context, args)
        report = build_for(context, project)
        table = next((t for t in report.tables() if t.id == args.table), None)
        if table is None:
            ids = ", ".join(t.id for t in report.tables())
            raise CliError(f"no table {args.table!r} — this report has: {ids}")
        if not args.out:
            csv.writer(context.out).writerows(sheets.csv_rows(table))
            return 0
        path = Path(args.out)
        sheets.write_table_csv(path, table)
        context.report(
            {"project": project.id, "table": table.id, "path": str(path), "rows": len(table.rows)},
            f"{project.title}: {table.title} ({len(table.rows)} rows) written to {path}",
        )
        return 0

    def tables(context: CliContext, args: Namespace) -> int:
        project = _project(context, args)
        report = build_for(context, project)
        tables_found = report.tables()
        width = max((len(table.id) for table in tables_found), default=2)
        context.report(
            {
                "project": project.id,
                "tables": [
                    {"id": table.id, "title": table.title, "rows": len(table.rows)}
                    for table in tables_found
                ],
            },
            "\n".join(
                f"{table.id:<{width}}  {table.title} ({len(table.rows)} rows)"
                for table in tables_found
            ),
        )
        return 0

    return [
        CliCommand(
            path=("report", "html"),
            summary="The project's plan as one HTML page: graph, order, estimates, steps.",
            configure=_configure_html,
            run=html,
            examples=(
                "dplanner report html search --out search.html",
                "dplanner report html > plan.html",
            ),
        ),
        CliCommand(
            path=("report", "site"),
            summary="Write the plan repository's site under reports/ — every project's page "
            "and an index. Never commits.",
            configure=_configure_site,
            run=site,
            examples=("dplanner report site", "dplanner report site --all"),
        ),
        CliCommand(
            path=("report", "xlsx"),
            summary="Every table of the report as one workbook, a sheet per table.",
            configure=_configure_out(required=True),
            run=xlsx,
            examples=("dplanner report xlsx search --out search.xlsx",),
        ),
        CliCommand(
            path=("report", "csv"),
            summary="One table of the report as CSV — stdout, or a file with --out.",
            configure=_configure_csv,
            run=csv_out,
            examples=(
                "dplanner report csv search --table order",
                "dplanner report csv search --table milestones --out milestones.csv",
            ),
        ),
        CliCommand(
            path=("report", "tables"),
            summary="The tables this project's report has, by id — what `report csv` takes.",
            configure=_configure_project,
            run=tables,
            examples=("dplanner report tables search",),
        ),
    ]


def _project(context: CliContext, args: Namespace) -> Project:
    if args.project:
        return find_project(context.library, args.project)
    return context.project


def _configure_project(parser: ArgumentParser) -> None:
    parser.add_argument(
        "project",
        nargs="?",
        default="",
        help="project id, folder name, or part of its title (default: the current project)",
    )


def _configure_html(parser: ArgumentParser) -> None:
    _configure_project(parser)
    parser.add_argument("--out", metavar="PATH", default="", help="write here instead of stdout")


def _configure_out(*, required: bool) -> Callable[[ArgumentParser], None]:
    def configure(parser: ArgumentParser) -> None:
        _configure_project(parser)
        parser.add_argument("--out", metavar="PATH", required=required, help="the file to write")

    return configure


def _configure_csv(parser: ArgumentParser) -> None:
    _configure_project(parser)
    parser.add_argument("--table", required=True, help="a table id — see `report tables`")
    parser.add_argument("--out", metavar="PATH", default="", help="write here instead of stdout")


def _configure_site(parser: ArgumentParser) -> None:
    _configure_project(parser)
    parser.add_argument(
        "--all",
        action="store_true",
        help="every repository in the library, not only the current project's",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="write the site into this directory instead of beside the plan or at the "
        "project's reporting location",
    )
