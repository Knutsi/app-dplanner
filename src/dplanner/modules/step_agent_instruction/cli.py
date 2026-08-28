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

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, step_arg
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import Node, Product, Project, Step, TextEdit
from dplanner.domain.store import FilesFor
from dplanner.modules.step_agent_instruction.aspect import (
    MODULE_ID,
    asset_paths,
    read,
    read_project,
)
from dplanner.modules.step_agent_instruction.prompt import Briefing, assemble


def step_author() -> StepAuthor:
    """`step add`'s instruction flag: the new step arrives ready to hand to an agent."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--agent-file",
            metavar="FILE",
            help="an agent instruction for the new step, or - for stdin",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.agent_file is None:
            return None
        body = body_from(args.agent_file)
        edit = TextEdit(step.id, MODULE_ID, 0, "", body)
        context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
        return StepAuthored({"agent": len(body)}, f"instruction: {len(body)} characters")

    return StepAuthor(configure, author, lambda args: args.agent_file == "-")


def lint_checks() -> list[LintCheck]:
    def missing_instructions(
        _product: Product, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        # A standing instruction covers every step, so it silences this check — the same
        # rule `agent prompt`'s guard applies.
        if read_project(project):
            return []
        return [
            LintFinding(
                check="agent.missing",
                subject_id=step.id,
                subject=step.title,
                message="no agent instruction and no standing one — "
                f"`dplanner agent set '{step.title}' --file -`, or "
                f"`dplanner agent set --project '{project.title}' --file -`",
            )
            for step in project.steps
            if not read(step)
        ]

    return [missing_instructions]


def commands(*, briefing: Briefing) -> list[CliCommand]:
    def _prompt(context: CliContext, args: Namespace) -> int:
        step = find_step(context.product, args.step)
        project = context.product.project_of(step.id)
        instruction = read(step)
        project_instruction = read_project(project)
        if not instruction and not project_instruction:
            raise CliError(
                f"{step.title!r} has no agent instruction and neither does its project — "
                f"set one with `dplanner agent set {step.title!r} --file …`, or a standing "
                f"one with `dplanner agent set --project {project.title!r} --file …`"
            )
        assembled = assemble(
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=instruction,
            parts=briefing.parts(context.product, step, context.store.files),
            sections=briefing.sections(context.product, step, context.store.files),
            epilogue=briefing.epilogue(step),
            preamble=briefing.preamble,
            project_instruction=project_instruction,
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
            summary="Print the full briefing for a step: instructions, description, "
            "requirements, branch and inherited context — everything, in one read.",
            configure=step_arg,
            run=_prompt,
            examples=("dplanner agent prompt 'Read the spec' --json",),
        ),
    ]


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
    body = body_from(args.file)
    node = _target(context, args)
    current = node.module_text.get(MODULE_ID, "")
    edit = TextEdit(node.id, MODULE_ID, 0, current, body)
    context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
    title = getattr(node, "title", "") or node.id
    context.report(
        {node.kind: node.id, "characters": len(body)}, f"{title}: {len(body)} characters"
    )
    return 0
