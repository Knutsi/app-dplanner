"""``dplanner describe …`` — a step's markdown, and the images it references."""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.assets import step_asset_commands
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_step, step_arg
from dplanner.domain.assets import assets, image_references
from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Project, Step, TextEdit
from dplanner.domain.store import FilesFor
from dplanner.modules.step_description.aspect import (
    MODULE_ID,
    enabled,
    read,
    write_state,
)


def lint_checks() -> list[LintCheck]:
    def missing_descriptions(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        return [
            LintFinding(
                check="description.missing",
                subject_id=step.id,
                subject=step.title,
                message=f"no description — `dplanner describe set '{step.title}' --file -`",
            )
            for step in project.steps
            # A step that has turned the aspect off is not missing a description; it has
            # said it does not want one. Lint reports gaps, not decisions.
            if enabled(step) and not read(step)
        ]

    def missing_images(_product: Library, project: Project, files: FilesFor) -> list[LintFinding]:
        """A description that embeds ![](assets/…) naming a file that is not beside the
        step — the reference an agent's briefing would carry into nothing."""
        findings = []
        for step in project.steps:
            references = image_references(read(step))
            if not references:
                continue
            try:
                known = set(assets(files(step.id, MODULE_ID)))
            except KeyError:
                known = set()  # A never-flushed step has no files yet.
            findings += [
                LintFinding(
                    check="description.image-missing",
                    subject_id=step.id,
                    subject=step.title,
                    message=f"its description references ![]({reference}) but no such "
                    f"file is beside the step — `dplanner describe attach "
                    f"'{step.title}' <file>` and use the printed path",
                )
                for reference in references
                if reference not in known
            ]
        return findings

    return [missing_descriptions, missing_images]


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("describe", "set"),
            summary="Replace a step's description with markdown from a file or stdin.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner describe set 'Read the spec' --file notes.md",
                "echo '# Notes' | dplanner describe set 'Read the spec' --file -",
            ),
        ),
        CliCommand(
            path=("describe", "clear"),
            summary="This step needs no description — a milestone, say. Stops lint asking.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner describe clear v1",),
        ),
        CliCommand(
            path=("describe", "show"),
            summary="Print a step's description.",
            configure=step_arg,
            run=_show,
            examples=("dplanner describe show 'Read the spec'",),
        ),
        *step_asset_commands(
            "describe",
            MODULE_ID,
            file_help="the image to copy in beside the step",
            attach_summary="Add an image beside a step and print the path to link to.",
            assets_summary="List the images a step keeps.",
            example_step="'Read the spec'",
            attached_text=lambda name: f"{name}\nReference it from the markdown as ![]({name})",
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _step(context: CliContext, needle: str) -> Step:
    return find_step(context.library, needle)


def step_author() -> StepAuthor:
    """`step add`'s description flag: the new step arrives already described."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--describe-file",
            metavar="FILE",
            help="a markdown description for the new step, or - for stdin",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.describe_file is None:
            return None
        body = body_from(args.describe_file)
        edit = TextEdit(step.id, MODULE_ID, 0, "", body)
        context.apply(EditTextCommand(edit, label="Set Description"))
        return StepAuthored({"described": len(body)}, f"description: {len(body)} characters")

    return StepAuthor(configure, author, lambda args: args.describe_file == "-")


def _set(context: CliContext, args: Namespace) -> int:
    body = body_from(args.file)
    step = _step(context, args.step)
    current = read(step)
    # One positioned edit over the whole document, labelled so a burst of GUI typing and a
    # whole-file replacement never coalesce into one undo step.
    edit = TextEdit(step.id, MODULE_ID, 0, current, body)
    context.apply(EditTextCommand(edit, label="Set Description"))
    context.report(
        {"step": step.id, "characters": len(body)},
        f"{step.title}: {len(body)} characters",
    )
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    """The opt-out, and the CLI half of the GUI's Type ▸ Description toggle.

    A description defaults to *on*, so deleting the prose would only mean "not written yet"
    and lint would keep asking. This says the step wants none — a milestone is a marker in
    the graph, not work to describe. Prose and mark go in one command, so one undo restores
    both, exactly as the GUI toggle does it.
    """
    step = _step(context, args.step)
    message = f"{step.title}: no description — this step wants none"
    if not enabled(step):
        # Already clear is success, and writes nothing.
        context.report({"step": step.id}, message)
        return 0
    prose = read(step)
    commands: list[Command] = [
        SetModuleDataCommand(step.id, MODULE_ID, write_state(False), label="Clear Description")
    ]
    if prose:
        commands.insert(
            0,
            EditTextCommand(TextEdit(step.id, MODULE_ID, 0, prose, ""), label="Clear Description"),
        )
    context.apply(
        commands[0] if len(commands) == 1 else CompositeCommand("Clear Description", commands)
    )
    context.report({"step": step.id}, message)
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = _step(context, args.step)
    body = read(step)
    context.report({"step": step.id, "markdown": body}, body or "(no description)")
    return 0
