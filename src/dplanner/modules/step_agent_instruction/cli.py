"""``dplanner agent …`` — the instruction an agent should read before doing a step.

The verbs an agent uses on itself: ``show`` before starting the work, ``set`` when the user
has told it something worth keeping for next time.
"""

from argparse import ArgumentParser, Namespace
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import TextEdit
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, read


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("agent", "show"),
            summary="Print how a step should be carried out. Read this before starting one.",
            configure=_one_step,
            run=_show,
            examples=("dplanner agent show 'Read the spec'",),
        ),
        CliCommand(
            path=("agent", "set"),
            summary="Replace a step's agent instruction from a file or stdin.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner agent set 'Read the spec' --file notes.md",
                "echo 'Follow FORMAT.md' | dplanner agent set 'Read the spec' --file -",
            ),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    body = read(step)
    context.report({"step": step.id, "markdown": body}, body or "(no instruction)")
    return 0


def _set(context: CliContext, args: Namespace) -> int:
    import sys

    if args.file == "-":
        body = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            raise CliError(f"no such file: {args.file}")
        body = path.read_text()

    step = find_step(context.product, args.step)
    current = read(step)
    edit = TextEdit(step.id, MODULE_ID, 0, current, body)
    context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
    context.report(
        {"step": step.id, "characters": len(body)}, f"{step.title}: {len(body)} characters"
    )
    return 0
