"""``dplanner start …`` — the step a plan begins from.

Only ``set`` and ``clear``, and ``step add --start`` for the origin authored in one call.
Neither refuses a shape: a start that waits on something, or a second start, is what
``graph.start`` reports — the same division ``feature set`` and ``scope.gathers-nothing``
keep, so a verb run halfway through reshaping a graph is never in the way.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_step, project_of_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor
from dplanner.planning.start import MODULE_ID, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("start", "set"),
            summary="Mark the step the plan begins from: no feature or milestone gathers it.",
            configure=step_arg,
            run=_set,
            examples=("dplanner start set 'Project start'",),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("start", "clear"),
            summary="A step is no longer the plan's start.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner start clear 'Project start'",),
            edits_graph=project_of_step,
        ),
    ]


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step):
        # Already set is success — state-setting verbs must survive batches.
        context.report({"step": step.id, "start": True}, f"{step.title}: already the start")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(True)))
    context.report({"step": step.id, "start": True}, f"{step.title}: is the start")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not read(step):
        context.report({"step": step.id, "start": False}, f"{step.title}: not the start")
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Start"))
    context.report({"step": step.id, "start": False}, f"{step.title}: no longer the start")
    return 0


def step_author() -> StepAuthor:
    """``step add``'s ``--start``: the origin, authored in the call that creates it.

    The one refusal is one the same call made: ``--after`` has already linked the step by
    the time the authors run, and a start that waits on something is a contradiction in a
    single line, so it aborts the whole ``step add`` with nothing written.
    """

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--start",
            action="store_true",
            help="this step is the one the plan begins from: it waits on nothing, and no "
            "feature or milestone gathers it",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not args.start:
            return None
        if context.library.requires(step.id):
            raise CliError("a start waits on nothing — drop --after, or leave off --start")
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(True)))
        return StepAuthored({"start": True}, "start")

    return StepAuthor(configure, author)


def lint_checks() -> list[LintCheck]:
    def start(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A start is where the work begins, and a plan begins in one place.

        Only prerequisites inside the project count: an id that resolves nowhere is
        ``graph.requires-dangling``'s, and the walks never leave the project either.
        """
        ids = {step.id for step in project.steps}
        starts = [step for step in project.steps if read(step)]
        found = []
        for step in starts:
            for before in library.requires(step.id):
                if before.id in ids:
                    found.append(
                        LintFinding(
                            check="graph.start",
                            subject_id=step.id,
                            subject=step.title,
                            message=f"is the start, but waits on {before.title!r} — a start "
                            f"is where the work begins; `dplanner step unlink "
                            f"'{step.title}' '{before.title}'`, or `dplanner start clear "
                            f"'{step.title}'`",
                        )
                    )
        if len(starts) > 1:
            for step in starts:
                others = " and ".join(repr(other.title) for other in starts if other is not step)
                found.append(
                    LintFinding(
                        check="graph.start",
                        subject_id=step.id,
                        subject=step.title,
                        message=f"is a start, and so is {others} — a plan begins in one "
                        f"place; `dplanner start clear` all but one",
                    )
                )
        return found

    return [start]
