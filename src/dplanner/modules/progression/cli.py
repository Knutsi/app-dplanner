"""``dplanner progression show`` — what can be launched right now, and how far along.

``order show`` answers what the graph *allows*; this answers where the work *is*: percent
done, what is stuck, waiting on a merge or a review, or running, the frontier ranked by
what finishing it unlocks, and what comes one move later. One derivation —
``domain/progression.py`` — feeds this verb, the Step statuses tab, the Control Centre and
``--json``, so none of them can disagree.

``--all`` is the Control Centre's question in the terminal: every project as one board, or
only the ones named, each row saying which project it is in and whether an agent works it.
The projects are positionals because ``--project`` is every verb's own option already
(``cli/main.py``), naming where a verb acts rather than what it reads.

The status and estimate readers arrive as functions from the composition root, the same
hand-over ``layout_cli.commands(days_for=…)`` uses — neither ``cli.py`` imports the other.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.progression import Progression, across, estimated_progress
from dplanner.domain.short_titles import UNTITLED

NO_PROJECT = "name a project, or pass --all for every project"
SEVERAL = "one project at a time — pass --all to read several as one board"


@dataclass(frozen=True)
class _Readers:
    status_for: Callable[[Step], str]
    counts_as_work: Callable[[Step], bool]
    days_for: Callable[[Step], float | None]
    auto_progresses: Callable[[Step, Step], bool]
    is_agent: Callable[[Step], bool]


def commands(
    *,
    status_in: Callable[[Library, date], Callable[[Step], str]],
    counts_as_work: Callable[[Step], bool],
    days_for: Callable[[Step], float | None],
    auto_progresses: Callable[[Step, Step], bool],
    is_agent: Callable[[Step], bool],
) -> list[CliCommand]:
    """``status_in`` reads a step's status in a library on a day — a wait is done once it is
    over, which only the day can say. ``auto_progresses`` says which links free their waiter
    from review on; ``is_agent`` whether an agent works a step, which every row says."""

    def show(context: CliContext, args: Namespace) -> int:
        status_for = status_in(context.library, context.clock.today())
        readers = _Readers(status_for, counts_as_work, days_for, auto_progresses, is_agent)
        return _show(context, args, readers)

    return [
        CliCommand(
            path=("progression", "show"),
            summary="What can be launched right now, and how far along — one project or all.",
            configure=_configure,
            run=show,
            examples=(
                "dplanner progression show search",
                "dplanner progression show search --json",
                "dplanner progression show --all",
                "dplanner progression show --all search billing",
            ),
        )
    ]


def _configure(parser: ArgumentParser) -> None:
    parser.add_argument(
        "projects",
        nargs="*",
        metavar="project",
        help="project id, folder name, or part of its title (several with --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="every project as one board, or only the ones named — each row names its project",
    )


def _projects(library: Library, args: Namespace) -> list[Project]:
    """The projects the board is made of, in library order: that is the order ties go."""
    if not args.all:
        if not args.projects:
            raise CliError(NO_PROJECT)
        if len(args.projects) > 1:
            raise CliError(SEVERAL)
        return [find_project(library, args.projects[0])]
    named = {find_project(library, needle).id for needle in args.projects}
    return [project for project in library.projects if not named or project.id in named]


def _show(context: CliContext, args: Namespace, readers: _Readers) -> int:
    library = context.library
    projects = _projects(library, args)
    found = across(
        library, projects, readers.status_for, readers.counts_as_work, readers.auto_progresses
    )
    weighted = estimated_progress(found, readers.days_for)

    def row(step: Step, **more: Any) -> dict[str, Any]:
        return {
            "id": step.id,
            "title": step.title,
            "project": library.project_of(step.id).id,
            "agent": readers.is_agent(step),
            **more,
        }

    def named(steps: tuple[Step, ...]) -> list[dict[str, Any]]:
        return [row(step) for step in steps]

    data: dict[str, Any] = {
        "percent": found.percent,
        "counts": {
            "done": len(found.done),
            "running": len(found.running),
            "review": len(found.review),
            "merge": len(found.merge),
            "attention": len(found.attention),
            "ready": len(found.ready),
            "upcoming": len(found.upcoming),
            "waiting": len(found.waiting),
        },
        "attention": named(found.attention),
        "merge": named(found.merge),
        "review": named(found.review),
        "running": named(found.running),
        "ready": [row(step, unlocks=found.unlocks[step.id]) for step in found.ready],
        "upcoming": [
            row(coming.step, after=[step.id for step in coming.after]) for coming in found.upcoming
        ],
        "waiting": named(found.waiting),
        "done": named(found.done),
    }
    if args.all:
        data["projects"] = [{"id": p.id, "title": p.title} for p in projects]
    else:
        data["project"] = projects[0].id
    if weighted is not None:
        finished, total = weighted
        data["estimated_days"] = {"done": finished, "total": total}
    spans = projects if args.all else ()
    context.report(data, _report(library, found, weighted, spans, readers.is_agent))
    return 0


def _report(
    library: Library,
    found: Progression,
    weighted: tuple[float, float] | None,
    spans: Sequence[Project],
    is_agent: Callable[[Step], bool],
) -> str:
    """The board as text. ``spans`` is the projects of a board across several — each row then
    leads with its project's name — and empty for one project's, which needs no name."""
    if not found.total:
        return "No steps yet."
    across_words = f" across {len(spans)} projects" if len(spans) > 1 else ""
    lines = [f"{found.percent:.0f}% done — {len(found.done)} of {found.total} steps{across_words}"]
    if weighted is not None:
        finished, total = weighted
        lines.append(f"{finished:g} of {total:g} estimated days done")

    def title(step: Step) -> str:
        return step.title or "Untitled step"

    def line(step: Step, *facts: str) -> str:
        """A row: its project where the board spans several, its title, and in brackets
        whether an agent works it and whatever else the section says about it."""
        said = ", ".join(("agent", *facts) if is_agent(step) else facts)
        where = f"{library.project_of(step.id).title or UNTITLED} · " if spans else ""
        return f"{where}{title(step)}  ({said})" if said else f"{where}{title(step)}"

    def unblocking(step: Step) -> str:
        unlocks = found.unlocks.get(step.id, 0)
        return line(step, f"unblocks {unlocks}") if unlocks else line(step)

    def section(label: str, rows: list[str]) -> None:
        if rows:
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  {row}" for row in rows)

    section("Blocked", [line(step) for step in found.attention])
    section("Ready to merge", [unblocking(step) for step in found.merge])
    section("Ready for review", [unblocking(step) for step in found.review])
    section("Running", [line(step) for step in found.running])
    section("Ready to start", [unblocking(step) for step in found.ready])
    section(
        "Up next",
        [
            line(coming.step, f"after {', '.join(title(step) for step in coming.after)}")
            for coming in found.upcoming
        ],
    )
    section("Waiting", [line(step) for step in found.waiting])
    section("Done", [line(step) for step in found.done])
    return "\n".join(lines)
