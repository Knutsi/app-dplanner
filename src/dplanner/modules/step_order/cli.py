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
from typing import Any

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_project
from dplanner.domain.ordering import Placed, placed

# What the first wave is called wherever it is shown: it is the answer to "what can I start
# now", and saying "wave 1" instead would make the reader work that out.
READY_LABEL = "Ready to start"


def wave_label(index: int) -> str:
    return READY_LABEL if index == 0 else f"Wave {index + 1}"


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("order", "show"),
            summary="The order a project's steps can be done in, with each step's index.",
            configure=_configure,
            run=_show,
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


def _show(context: CliContext, args: Namespace) -> int:
    product = context.product
    project = find_project(product, args.project)
    found = placed(product, project)
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
    context.report(data, _table(found) or "No steps yet.")
    return 0


def _table(order: list[Placed]) -> str:
    """The same three columns the window shows, so the two answers look like one answer."""
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
