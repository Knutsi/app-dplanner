"""``dplanner describe …`` — a step's markdown, and the images it references."""

from argparse import ArgumentParser, Namespace
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lint import FilesFor, LintCheck, LintFinding
from dplanner.cli.lookup import find_step
from dplanner.domain.assets import assets, attach
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import Product, Project, Step, TextEdit
from dplanner.modules.step_description.aspect import MODULE_ID, image_references, read


def lint_checks() -> list[LintCheck]:
    def missing_descriptions(
        _product: Product, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        return [
            LintFinding(
                check="description.missing",
                subject_id=step.id,
                subject=step.title,
                message=f"no description — `dplanner describe set '{step.title}' --file -`",
            )
            for step in project.steps
            if not read(step)
        ]

    def missing_images(
        _product: Product, project: Project, files: FilesFor
    ) -> list[LintFinding]:
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
            path=("describe", "show"),
            summary="Print a step's description.",
            configure=_one_step,
            run=_show,
            examples=("dplanner describe show 'Read the spec'",),
        ),
        CliCommand(
            path=("describe", "attach"),
            summary="Add an image beside a step and print the path to link to.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner describe attach 'Read the spec' diagram.png",),
        ),
        CliCommand(
            path=("describe", "assets"),
            summary="List the images a step keeps.",
            configure=_one_step,
            run=_assets,
            examples=("dplanner describe assets 'Read the spec'",),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _configure_attach(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("image", help="the file to copy in beside the step")


def _step(context: CliContext, needle: str) -> Step:
    return find_step(context.product, needle)


def _set(context: CliContext, args: Namespace) -> int:
    import sys

    if args.file == "-":
        body = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            raise CliError(f"no such file: {args.file}")
        body = path.read_text()

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


def _show(context: CliContext, args: Namespace) -> int:
    step = _step(context, args.step)
    body = read(step)
    context.report({"step": step.id, "markdown": body}, body or "(no description)")
    return 0


def _attach(context: CliContext, args: Namespace) -> int:
    source = Path(args.image)
    if not source.is_file():
        raise CliError(f"no such file: {args.image}")
    step = _step(context, args.step)
    name = attach(context.store.files(step.id, MODULE_ID), source.read_bytes(), source.name)
    context.report(
        {"step": step.id, "asset": name},
        f"{name}\nReference it from the markdown as ![]({name})",
    )
    return 0


def _assets(context: CliContext, args: Namespace) -> int:
    step = _step(context, args.step)
    names = assets(context.store.files(step.id, MODULE_ID))
    context.report({"step": step.id, "assets": names}, "\n".join(names) or "(none)")
    return 0
