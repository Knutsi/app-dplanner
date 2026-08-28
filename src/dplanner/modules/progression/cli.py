"""``dplanner progression show`` — what can be launched right now, and how far along.

``order show`` answers what the graph *allows*; this answers where the work *is*: percent
done, what is running or stuck, the frontier ranked by what finishing it unlocks, and
what comes one move later. One derivation — ``domain/progression.py`` — feeds this verb,
the tab and ``--json``, so the three can never disagree.

The status and estimate readers arrive as functions from the composition root, the same
hand-over ``layout_cli.commands(days_for=…)`` uses — neither ``cli.py`` imports the other.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from typing import Any

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_project
from dplanner.domain.model import Step
from dplanner.domain.progression import Progression, estimated_progress, progression


def commands(
    *,
    status_for: Callable[[Step], str],
    days_for: Callable[[Step], float | None],
) -> list[CliCommand]:
    def show(context: CliContext, args: Namespace) -> int:
        return _show(context, args, status_for, days_for)

    return [
        CliCommand(
            path=("progression", "show"),
            summary="What can be launched right now, and how far along a project is.",
            configure=_configure,
            run=show,
            examples=(
                "dplanner progression show search",
                "dplanner progression show search --json",
            ),
        )
    ]


def _configure(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _show(
    context: CliContext,
    args: Namespace,
    status_for: Callable[[Step], str],
    days_for: Callable[[Step], float | None],
) -> int:
    library = context.library
    project = find_project(library, args.project)
    found = progression(library, project, status_for)
    weighted = estimated_progress(found, days_for)

    def named(steps: tuple[Step, ...]) -> list[dict[str, Any]]:
        return [{"id": step.id, "title": step.title} for step in steps]

    data: dict[str, Any] = {
        "project": project.id,
        "percent": found.percent,
        "counts": {
            "done": len(found.done),
            "running": len(found.running),
            "attention": len(found.attention),
            "ready": len(found.ready),
            "upcoming": len(found.upcoming),
            "waiting": len(found.waiting),
        },
        "attention": named(found.attention),
        "running": named(found.running),
        "ready": [
            {"id": row.step.id, "title": row.step.title, "unlocks": row.unlocks}
            for row in found.ready
        ],
        "upcoming": [
            {
                "id": coming.step.id,
                "title": coming.step.title,
                "after": [step.id for step in coming.after],
            }
            for coming in found.upcoming
        ],
        "waiting": named(found.waiting),
        "done": named(found.done),
    }
    if weighted is not None:
        finished, total = weighted
        data["estimated_days"] = {"done": finished, "total": total}
    context.report(data, _report(found, weighted))
    return 0


def _report(found: Progression, weighted: tuple[float, float] | None) -> str:
    if not found.total:
        return "No steps yet."
    lines = [f"{found.percent:.0f}% done — {len(found.done)} of {found.total} steps"]
    if weighted is not None:
        finished, total = weighted
        lines.append(f"{finished:g} of {total:g} estimated days done")

    def title(step: Step) -> str:
        return step.title or "Untitled step"

    def section(label: str, rows: list[str]) -> None:
        if rows:
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  {row}" for row in rows)

    section("Needs attention", [title(step) for step in found.attention])
    section("Running", [title(step) for step in found.running])
    section(
        "Ready to launch",
        [
            f"{title(row.step)}  (unblocks {row.unlocks})" if row.unlocks else title(row.step)
            for row in found.ready
        ],
    )
    section(
        "Up next",
        [
            f"{title(coming.step)}  (after {', '.join(title(step) for step in coming.after)})"
            for coming in found.upcoming
        ],
    )
    section("Waiting", [title(step) for step in found.waiting])
    section("Done", [title(step) for step in found.done])
    return "\n".join(lines)
