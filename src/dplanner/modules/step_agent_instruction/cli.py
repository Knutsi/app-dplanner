"""``dplanner agent …`` — the instruction an agent should read before doing a step.

The verbs an agent uses on itself: ``show`` before starting the work, ``set`` when the user
has told it something worth keeping for next time, ``prompt`` for the whole assembled
briefing — project instruction, step instruction, inherited context — which is also what
Run Agent in the window launches with. ``show``/``set`` take either a step or ``--project``,
because the aspect lives at both levels and the verbs should not care.

``commands()`` takes the context assembly as typed parameters, supplied by the composition
root — the CLI-side twin of a module ``Deps`` callback, and the same generalisation
``skill_commands(specs, described)`` already made: a ``cli.py`` never imports another
module, so what crosses modules arrives as arguments.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import Node, Product, Step, StepId, TextEdit
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.step_agent_instruction.aspect import (
    MODULE_ID,
    asset_paths,
    read,
    read_project,
)
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
            project_instruction=read_project(project),
            project_files=asset_paths(context.store.files, project.id),
            instruction_files=asset_paths(context.store.files, step.id),
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
            summary="Print how a step — or with --project, a whole project — should be "
            "carried out. Read this before starting a step.",
            configure=_one_target,
            run=_show,
            examples=(
                "dplanner agent show 'Read the spec'",
                "dplanner agent show --project 'Search rewrite'",
            ),
        ),
        CliCommand(
            path=("agent", "set"),
            summary="Replace a step's — or with --project, the project's standing — agent "
            "instruction from a file or stdin.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner agent set 'Read the spec' --file notes.md",
                "echo 'Follow FORMAT.md' | dplanner agent set --project Rewrite --file -",
            ),
        ),
        CliCommand(
            path=("agent", "prompt"),
            summary="Print the full briefing for a step: project and step instructions "
            "plus inherited context.",
            configure=_one_step,
            run=_prompt,
            examples=("dplanner agent prompt 'Read the spec' --json",),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _one_target(parser: ArgumentParser) -> None:
    parser.add_argument(
        "step", nargs="?", help="step id, folder name, or part of its title"
    )
    parser.add_argument(
        "--project",
        help="a project instead: its standing instruction, prepended to every briefing",
    )


def _configure_set(parser: ArgumentParser) -> None:
    _one_target(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _target(context: CliContext, args: Namespace) -> Node:
    """The step or the project the verb addresses — exactly one of the two."""
    if (args.step is None) == (args.project is None):
        raise CliError("name a step, or --project, but not both")
    if args.project is not None:
        return find_project(context.product, args.project)
    return find_step(context.product, args.step)


def _show(context: CliContext, args: Namespace) -> int:
    node = _target(context, args)
    body = node.module_text.get(MODULE_ID, "")
    context.report({node.kind: node.id, "markdown": body}, body or "(no instruction)")
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

    node = _target(context, args)
    current = node.module_text.get(MODULE_ID, "")
    edit = TextEdit(node.id, MODULE_ID, 0, current, body)
    context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
    title = getattr(node, "title", "") or node.id
    context.report(
        {node.kind: node.id, "characters": len(body)}, f"{title}: {len(body)} characters"
    )
    return 0
