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
from dplanner.domain.ordering import waves

# What the first wave is called wherever it is shown: it is the answer to "what can I start
# now", and saying "wave 1" instead would make the reader work that out.
READY_LABEL = "Ready to start"


def wave_label(index: int) -> str:
    return READY_LABEL if index == 0 else f"Wave {index + 1}"


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("order", "show"),
            summary="The order a project's steps can be done in, in waves.",
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
    found = waves(product, project)
    if args.ready:
        found = found[:1]

    data: dict[str, Any] = {
        "project": project.id,
        "waves": [
            [{"id": step.id, "title": step.title, "wave": index + 1} for step in wave]
            for index, wave in enumerate(found)
        ],
    }
    lines: list[str] = []
    for index, wave in enumerate(found):
        lines.append(f"{wave_label(index)}:")
        lines.extend(f"  {step.title}  {step.id[:8]}" for step in wave)
    context.report(data, "\n".join(lines) or "No steps yet.")
    return 0
