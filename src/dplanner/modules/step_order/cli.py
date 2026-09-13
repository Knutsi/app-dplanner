"""``dplanner order show`` — in what order a project's steps can be done.

A noun of its own rather than a flag on ``step list``, because "what order can this be done
in" is a different question from "what steps are there", and because the module that owns the
concept owns its verbs — the same reasoning that gives ``estimate``, ``ticket`` and
``describe`` theirs.

This verb is what "always available" means without a file. The order is derived on the spot,
so an agent asking for it gets the current answer and can never read a stale one.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from typing import Any

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_project
from dplanner.domain.model import Step
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.schedule import volume_words


def wave_label(index: int) -> str:
    """What a wave is called wherever it is shown — the table, the export, this verb.

    The first wave was called *Ready to start* until the execution board took that name:
    one phrase answering both "nothing in the graph is before this" and "nothing this waits
    on is left undone" is the distinction the board exists to draw.
    """
    return f"Wave {index + 1}"


def commands(*, days_for: Callable[[Step], float | None]) -> list[CliCommand]:
    return [
        CliCommand(
            path=("order", "show"),
            summary="The order a project's steps can be done in, with each step's index.",
            configure=_configure,
            run=lambda context, args: _show(context, args, days_for),
            examples=(
                "dplanner order show search",
                "dplanner order show search --json",
                "dplanner order show search --ready",
            ),
        )
    ]


def _configure(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="only the steps with nothing left to wait on",
    )


def _show(context: CliContext, args: Namespace, days_for: Callable[[Step], float | None]) -> int:
    library = context.library
    project = find_project(library, args.project)
    found = placed(library, project)
    if args.ready:
        found = [place for place in found if place.wave == 1]

    data: dict[str, Any] = {
        "project": project.id,
        "steps": [
            {
                "index": place.index,
                "wave": place.wave,
                "id": place.step.id,
                "title": place.step.title,
            }
            for place in found
        ],
    }
    estimates = [days_for(place.step) for place in found]
    sized = [days for days in estimates if days is not None]
    volume = volume_words(sum(sized), len(estimates), len(estimates) - len(sized))
    data |= {"days": sum(sized), "unestimated": len(estimates) - len(sized)}
    table = _table(found)
    context.report(data, f"{table}\n\n{volume}" if table else "No steps yet.")
    return 0


def _table(order: list[Placed]) -> str:
    """The graph's three columns — the order, and nothing that depends on a date.

    A serial calendar is what this verb stays out of: ``dplanner schedule show`` dates the
    steps and ``schedule matrix`` simulates them, and a column of dates here would be a
    third answer nobody asked for. The *total* under the table is the exception, because a
    volume is the one thing an order can state without pretending to know who does the work
    — and it is the sentence the tab, ``estimate rollup`` and the Estimates tab all print.
    """
    if not order:
        return ""
    width = max(len(place.step.title or "Untitled step") for place in order)
    rows = [f"{'#':>3}  {'Step':<{width}}  Wave"]
    rows += [
        f"{place.index:>3}  {place.step.title or 'Untitled step':<{width}}  "
        f"{wave_label(place.wave - 1)}"
        for place in order
    ]
    return "\n".join(rows)
