"""``dplanner agent …`` — mark steps for agent execution, and read their briefings.

The description is the briefing's instructions: ``agent on`` is all most agent steps need
beside ``describe set``. ``agent set`` writes the *separate* instruction — only for a step
whose how-to-execute genuinely differs from its description — or, with ``--for-project``,
the project's standing instruction prepended to every briefing. ``prompt`` prints the whole
assembled briefing, which is also what Run Agent in the window launches with.

``commands()`` takes the context assembly as typed parameters, supplied by the composition
root — the CLI-side twin of a module ``Deps`` callback, and the same generalisation
``skill_commands(specs, described)`` already made: a ``cli.py`` never imports another
module, so what crosses modules arrives as arguments.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, step_arg
from dplanner.domain.commands import EditTextCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Node, Project, Step, TextEdit
from dplanner.domain.repositories import repository_facts
from dplanner.domain.shelf import turn_off, turn_on
from dplanner.domain.store import FilesFor
from dplanner.modules.step_agent_instruction.aspect import (
    MODULE_ID,
    asset_paths,
    enabled,
    read,
    read_project,
    separate_instruction,
    uses_worktree,
    with_worktree,
    write_state,
)
from dplanner.modules.step_agent_instruction.prompt import Briefing, assemble


def step_author() -> StepAuthor:
    """`step add`'s agent flags: the new step arrives ready to hand to an agent.

    ``--agent`` marks the step (its description is the briefing); ``--agent-file`` also
    writes a separate instruction for the rare step whose execution guidance differs.
    """

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--agent",
            action="store_true",
            help="mark the new step for agent execution; its description is the briefing",
        )
        parser.add_argument(
            "--agent-file",
            metavar="FILE",
            help="a separate agent instruction, or - for stdin — only when how-to-execute"
            " differs from the description",
        )
        parser.add_argument(
            "--no-worktree",
            dest="no_worktree",
            action="store_true",
            help="the agent works in the checkout itself rather than a fresh worktree —"
            " only for a step that must (implies --agent)",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not (args.agent or args.agent_file is not None or args.no_worktree):
            return None
        worktree = not args.no_worktree
        note = "agent step" if worktree else "agent step, in the checkout itself"
        data: dict[str, object] = {"agent": True, "worktree": worktree}
        if args.agent_file is not None:
            body = body_from(args.agent_file)
            edit = TextEdit(step.id, MODULE_ID, 0, "", body)
            context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
            data["instruction"] = len(body)
            note += f", separate instruction: {len(body)} characters"
        context.apply(
            SetModuleDataCommand(
                step.id,
                MODULE_ID,
                write_state(True, separate=args.agent_file is not None, worktree=worktree),
                label="Set Agent Aspect",
            )
        )
        return StepAuthored(data, note)

    return StepAuthor(configure, author, lambda args: args.agent_file == "-")


def lint_checks(*, described: Callable[[Step], bool]) -> list[LintCheck]:
    """``described`` is the description aspect's reader, handed over by the composition
    root — this file never imports another module's."""

    def missing_briefing(
        _product: Library, project: Project, _files: FilesFor
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
                message="an agent step with nothing to brief it — "
                f"`dplanner describe set '{step.title}' --file -`, or a separate "
                f"instruction with `dplanner agent set '{step.title}' --file -`",
            )
            for step in project.steps
            if enabled(step) and not read(step) and not described(step)
        ]

    return [missing_briefing]


def commands(*, briefing: Briefing) -> list[CliCommand]:
    def _prompt(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        project = context.library.project_of(step.id)
        if not enabled(step):
            raise CliError(
                f"{step.title!r} is not an agent step — mark it with "
                f"`dplanner agent on {step.title!r}`"
            )
        instruction = briefing.instruction(context.library, step, context.store.files)
        project_instruction = read_project(project)
        directory = context.store.project_dir(project.id)
        facts = repository_facts(project, directory, context.store.checkout_of(project.id))
        if not instruction.body and not instruction.files and not project_instruction:
            raise CliError(
                f"{step.title!r} has nothing to brief an agent with — describe it with "
                f"`dplanner describe set {step.title!r} --file …`, or set a standing "
                f"instruction with `dplanner agent set --for-project {project.title!r} "
                "--file …`"
            )
        assembled = assemble(
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=instruction.body,
            parts=briefing.parts(context.library, step, context.store.files),
            sections=briefing.sections(context.library, step, context.store.files),
            project_sections=briefing.project_sections(context.library, step, context.store.files),
            epilogue=briefing.epilogue(step),
            preamble=briefing.preamble(step, uses_worktree(step), facts),
            project_instruction=project_instruction,
            project_files=asset_paths(context.store.files, project.id),
            instruction_files=instruction.files,
        )
        data = {
            "step": step.id,
            "root": str(directory),
            # Where the plan lives, which code it plans, and where that code is here —
            # so an agent that wants to know never derives them.
            "plan": str(facts.plan_root or ""),
            "repository": facts.repository,
            "checkout": str(facts.checkout) if facts.checkout is not None else "",
            "prompt": assembled.text,
            "files": list(assembled.files),
        }
        context.report(data, assembled.text)
        return 0

    return [
        CliCommand(
            path=("agent", "on"),
            summary="Mark a step for agent execution; its description is the briefing's "
            "instructions.",
            configure=step_arg,
            run=_on,
            examples=("dplanner agent on 'Read the spec'",),
        ),
        CliCommand(
            path=("agent", "off"),
            summary="Unmark an agent step; a separate instruction is kept for marking it again.",
            configure=step_arg,
            run=_off,
            examples=("dplanner agent off 'Read the spec'",),
        ),
        CliCommand(
            path=("agent", "show"),
            summary="Print a step's separate agent instruction — or with --for-project, "
            "the project's standing one.",
            configure=_one_target,
            run=_show,
            examples=(
                "dplanner agent show 'Read the spec'",
                "dplanner agent show --for-project 'Search rewrite'",
            ),
        ),
        CliCommand(
            path=("agent", "set"),
            summary="Write a step's separate agent instruction — only when how-to-execute "
            "differs from its description — or with --for-project, the project's standing "
            "instruction; --clear drops it while keeping the agent mark.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner agent set 'Read the spec' --file notes.md",
                "echo 'Follow FORMAT.md' | dplanner agent set --for-project Rewrite --file -",
                "dplanner agent set 'Read the spec' --clear",
            ),
        ),
        CliCommand(
            path=("agent", "worktree"),
            summary="Whether Run Agent puts this step's agent in a fresh git worktree on its"
            " own branch (on by default); off only for a step that must work in the checkout"
            " the window shows.",
            configure=_configure_worktree,
            run=_worktree,
            examples=("dplanner agent worktree 'Cut the release' off",),
        ),
        CliCommand(
            path=("agent", "prompt"),
            summary="Print the full briefing for a step: instructions, requirements, "
            "branch and inherited context — everything, in one read.",
            configure=step_arg,
            run=_prompt,
            examples=("dplanner agent prompt 'Read the spec' --json",),
        ),
    ]


def _one_target(parser: ArgumentParser) -> None:
    parser.add_argument("step", nargs="?", help="step id, folder name, or part of its title")
    parser.add_argument(
        "--for-project",
        dest="for_project",
        nargs="?",
        const="",
        default=None,
        metavar="PROJECT",
        help="the project instead: its standing instruction, prepended to every "
        "briefing (defaults to the current project)",
    )


def _configure_worktree(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("worktree", choices=("on", "off"), help="fresh worktree, or the checkout")


def _worktree(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    wanted = args.worktree == "on"
    if not enabled(step):
        raise CliError(
            f"{step.title!r} is not an agent step — mark it with `dplanner agent on {step.title!r}`"
        )
    where = "a fresh worktree" if wanted else "the checkout itself"
    if uses_worktree(step) == wanted:
        context.report({"step": step.id, "worktree": wanted}, f"{step.title}: already {where}")
        return 0
    label = "Agent Worktree On" if wanted else "Agent Worktree Off"
    context.apply(
        SetModuleDataCommand(step.id, MODULE_ID, with_worktree(step, wanted), label=label)
    )
    context.report({"step": step.id, "worktree": wanted}, f"{step.title}: {where}")
    return 0


def _configure_set(parser: ArgumentParser) -> None:
    _one_target(parser)
    parser.add_argument("--file", help="a markdown file, or - for stdin")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="drop the separate instruction; the description becomes the briefing again"
        " — the agent mark stays",
    )


def _target(context: CliContext, args: Namespace) -> Node:
    """The step or the project the verb addresses — exactly one of the two."""
    if (args.step is None) == (args.for_project is None):
        raise CliError("name a step, or --for-project, but not both")
    if args.for_project is not None:
        if args.for_project:
            return find_project(context.library, args.for_project)
        return context.project
    return find_step(context.library, args.step, context.current)


def _on(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if enabled(step):
        context.report({"step": step.id, "agent": True}, f"{step.title}: already an agent step")
        return 0
    # The shelf first: `agent off` kept a separate instruction, and on brings it back.
    context.apply(turn_on(step, MODULE_ID, fresh=write_state(True), label="Add Agent"))
    context.report({"step": step.id, "agent": True}, f"{step.title}: agent step")
    return 0


def _off(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not enabled(step):
        # Already in the target state is success — a batch of offs must survive a step
        # somebody else already unmarked.
        context.report(
            {"step": step.id, "agent": False}, f"{step.title}: already not an agent step"
        )
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Agent"))
    context.report({"step": step.id, "agent": False}, f"{step.title}: not an agent step")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    node = _target(context, args)
    body = node.module_text.get(MODULE_ID, "")
    if node.kind != "step":
        context.report({node.kind: node.id, "markdown": body}, body or "(no instruction)")
        return 0
    step = context.library.step(node.id)
    data = {
        "step": step.id,
        "markdown": body,
        "agent": enabled(step),
        "separate": separate_instruction(step),
        "worktree": uses_worktree(step),
    }
    if body:
        context.report(data, body)
    elif enabled(step):
        context.report(
            data,
            "(no separate instruction — the description is the briefing's instructions)",
        )
    else:
        context.report(data, f"(not an agent step — `dplanner agent on {step.title!r}`)")
    return 0


def _set(context: CliContext, args: Namespace) -> int:
    if (args.file is None) == (not args.clear):
        raise CliError("give --file or --clear")
    if args.clear:
        return _clear_instruction(context, args)
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


def _clear_instruction(context: CliContext, args: Namespace) -> int:
    """The atomic way back from a separate instruction: text and ``separate`` flag both
    go, the agent mark stays — the two-verb off/on dance briefly unmarked the step."""
    node = _target(context, args)
    title = getattr(node, "title", "") or node.id
    current = node.module_text.get(MODULE_ID, "")
    if node.kind != "step":
        if current:
            edit = TextEdit(node.id, MODULE_ID, 0, current, "")
            context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
        context.report({node.kind: node.id, "characters": 0}, f"{title}: no standing instruction")
        return 0
    step = context.library.step(node.id)
    was_agent = enabled(step)
    if current:
        edit = TextEdit(step.id, MODULE_ID, 0, current, "")
        context.apply(EditTextCommand(edit, label="Set Agent Instruction"))
    if was_agent:
        # Re-assert the bare mark: it drops a stored ``separate`` flag, and keeps a step
        # whose mark was implied by the text just cleared an agent step.
        context.apply(
            SetModuleDataCommand(
                step.id, MODULE_ID, write_state(True), label="Use Description as Instructions"
            )
        )
        context.report(
            {"step": step.id, "agent": True, "separate": False},
            f"{title}: the description is the briefing's instructions",
        )
    else:
        context.report(
            {"step": step.id, "agent": False, "separate": False},
            f"{title}: no separate instruction",
        )
    return 0
