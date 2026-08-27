"""``dplanner agent …`` — the instruction an agent should read before doing a step.

The verbs an agent uses on itself: ``show`` before starting the work, ``set`` when the user
has told it something worth keeping for next time, ``prompt`` for the whole assembled
briefing — instruction plus inherited context — which is also what Run Agent in the window
launches with.

``commands()`` takes the context assembly as typed parameters, supplied by the composition
root — the CLI-side twin of a module ``Deps`` callback, and the same generalisation
``skill_commands(specs, described)`` already made: a ``cli.py`` never imports another
module, so what crosses modules arrives as arguments.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import Product, Step, StepId, TextEdit
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, read
from dplanner.modules.step_agent_instruction.prompt import PromptPart, assemble

# (product, step, files) -> the context blocks the prompt should carry. ``files`` is the
# store's file lookup, passed through so the parts can name real asset paths.
PartsFor = Callable[
    [Product, Step, Callable[[StepId, str], ModuleFileArea]], Sequence[PromptPart]
]
EpilogueFor = Callable[[Step], str]


def _no_parts(
    _product: Product, _step: Step, _files: Callable[[StepId, str], ModuleFileArea]
) -> Sequence[PromptPart]:
    return ()


def _no_epilogue(_step: Step) -> str:
    return ""


def commands(
    prompt_parts: PartsFor = _no_parts,
    epilogue: EpilogueFor = _no_epilogue,
    preamble: str = "",
) -> list[CliCommand]:
    def _prompt(context: CliContext, args: Namespace) -> int:
        step = find_step(context.product, args.step)
        instruction = read(step)
        if not instruction:
            raise CliError(f"{step.title!r} has no agent instruction")
        project = context.product.project_of(step.id)
        assembled = assemble(
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=instruction,
            parts=prompt_parts(context.product, step, context.store.files),
            epilogue=epilogue(step),
            preamble=preamble,
        )
        data = {
            "step": step.id,
            "root": str(context.store.storage.root),
            "prompt": assembled.text,
            "files": list(assembled.files),
        }
        context.report(data, assembled.text)
        return 0

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
        CliCommand(
            path=("agent", "prompt"),
            summary="Print the full briefing for a step: instruction plus inherited context.",
            configure=_one_step,
            run=_prompt,
            examples=("dplanner agent prompt 'Read the spec' --json",),
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
