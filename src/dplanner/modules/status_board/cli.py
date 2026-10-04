"""``dplanner progression show`` — what can be launched right now, and how far along.

``order show`` answers what the graph *allows*; this answers where the work *is*: percent
done, what is stuck, waiting on a merge or a review, or running, the frontier ranked by
what finishing it unlocks, and what comes one move later. One derivation —
``planning/progression.py`` — feeds this verb, the Step statuses tab, the Control Centre and
``--json``, so none of them can disagree.

``--all`` is the Control Centre's question in the terminal: every project as one board, or
only the ones named, each row saying which project it is in and whether an agent works it.
The projects are positionals because ``--project`` is every verb's own option already
(``cli/main.py``), naming where a verb acts rather than what it reads.

The status reader arrives as a function from the composition root — a wait is over only
on its day, and a wait is still a module's — and the estimate is the planning tier's own.
So does what is **due**: the agent steps a window that launches what becomes due would start
on its own, marked on their rows, and **Waits for you** — running work whose agent waits on
a person — which ``asks_person`` splits from Running. **Taken by an agent** is the other
half of that line: work under review that an agent takes on from there, which ``is_agent``
splits from Ready for review, so that section names a person's turn alone.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.short_titles import UNTITLED
from dplanner.planning.progression import Progression, across, estimated_progress
from dplanner.planning.status import Status

NO_PROJECT = "name a project, or pass --all for every project"
SEVERAL = "one project at a time — pass --all to read several as one board"


@dataclass(frozen=True)
class _Readers:
    status_for: Callable[[Step], Status]
    counts_as_work: Callable[[Step], bool]
    auto_progresses: Callable[[Step, Step], bool]
    is_agent: Callable[[Step], bool]
    asks_person: Callable[[Step], bool]
    due: Callable[[Library, Project, Callable[[Step], Status]], Sequence[Step]]


def commands(
    *,
    status_in: Callable[[Library, date], Callable[[Step], Status]],
    counts_as_work: Callable[[Step], bool],
    auto_progresses: Callable[[Step, Step], bool],
    is_agent: Callable[[Step], bool],
    asks_person: Callable[[Step], bool],
    due: Callable[[Library, Project, Callable[[Step], Status]], Sequence[Step]],
) -> list[CliCommand]:
    """``status_in`` reads a step's status in a library on a day — a wait is done once it is
    over, which only the day can say. ``auto_progresses`` says which links free their waiter
    from review on; ``is_agent`` whether an agent works a step, which every row says;
    ``asks_person`` whether a running step's agent waits on a person; ``due`` which steps of
    a project a window would launch on its own, read with the day's statuses."""

    def show(context: CliContext, args: Namespace) -> int:
        status_for = status_in(context.library, context.clock.today())
        readers = _Readers(status_for, counts_as_work, auto_progresses, is_agent, asks_person, due)
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
        library,
        projects,
        readers.status_for,
        readers.counts_as_work,
        readers.auto_progresses,
        readers.asks_person,
        readers.is_agent,
    )
    weighted = estimated_progress(found)
    due = {
        step.id
        for project in projects
        for step in readers.due(library, project, readers.status_for)
    }

    def row(step: Step, **more: Any) -> dict[str, Any]:
        return {
            "id": step.id,
            "title": step.title,
            "project": library.project_of(step.id).id,
            "agent": readers.is_agent(step),
            "due": step.id in due,
            **more,
        }

    def named(steps: tuple[Step, ...]) -> list[dict[str, Any]]:
        return [row(step) for step in steps]

    data: dict[str, Any] = {
        "percent": found.percent,
        "counts": {
            "done": len(found.done),
            "running": len(found.running),
            "asking": len(found.asking),
            "review": len(found.review),
            "taken": len(found.taken),
            "merge": len(found.merge),
            "attention": len(found.attention),
            "ready": len(found.ready),
            "upcoming": len(found.upcoming),
            "waiting": len(found.waiting),
        },
        "attention": named(found.attention),
        "asking": named(found.asking),
        "merge": named(found.merge),
        "review": named(found.review),
        "taken": named(found.taken),
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
    context.report(data, _report(library, found, weighted, spans, readers.is_agent, due))
    return 0


def _report(
    library: Library,
    found: Progression,
    weighted: tuple[float, float] | None,
    spans: Sequence[Project],
    is_agent: Callable[[Step], bool],
    due: Collection[StepId],
) -> str:
    """The board as text. ``spans`` is the projects of a board across several — each row then
    leads with its project's name — and empty for one project's, which needs no name. A row
    in ``due`` says so: a window that launches what becomes due starts it."""
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
        whether an agent works it, whether it is due, and whatever else the section says."""
        marks = (*(("agent",) if is_agent(step) else ()), *(("due",) if step.id in due else ()))
        said = ", ".join((*marks, *facts))
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
    section("Waits for you", [line(step) for step in found.asking])
    section("Ready to merge", [unblocking(step) for step in found.merge])
    section("Ready for review", [unblocking(step) for step in found.review])
    section("Running", [line(step) for step in found.running])
    section("Taken by an agent", [line(step) for step in found.taken])
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
