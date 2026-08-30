"""``dplanner check …`` — the step type that gathers every test it waits on.

``check show`` needs to know what a test *is*, which is another module's business. It
arrives as a keyword-only parameter closed over in one inner wrapper — the injection style
``modules/progression/cli.py`` established, so this file still imports no module but its own.
"""

from argparse import Namespace
from collections.abc import Callable, Sequence

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.step_check.aspect import MODULE_ID, read, write

# What a check covers, as the module that owns tests answers it: (id, title, step title).
type CoveredTest = tuple[str, str, str]
type CoveredBy = Callable[[Library, Project, StepId], Sequence[CoveredTest]]


def commands(*, covered_by: CoveredBy) -> list[CliCommand]:
    def show(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        # The step names its project, so this reads the same with or without a current one.
        found = covered_by(context.library, context.library.project_of(step.id), step.id)
        data = {
            "step": step.id,
            "check": read(step),
            "tests": [
                {"id": test_id, "title": title, "step_title": owner}
                for test_id, title, owner in found
            ],
        }
        width = max((len(test_id) for test_id, _t, _o in found), default=0)
        lines = [f"{test_id:<{width}}  {title}  ({owner})" for test_id, title, owner in found]
        headline = f"{step.title}: {len(found)} test{'' if len(found) == 1 else 's'}"
        if not read(step):
            headline += " (not a check — `dplanner check set` makes it one)"
        context.report(data, "\n".join([headline, *lines]))
        return 0

    return [
        CliCommand(
            path=("check", "set"),
            summary="Mark a step as a check: it gathers every test it waits on.",
            configure=step_arg,
            run=_set,
            examples=("dplanner check set 'Pre-release check'",),
        ),
        CliCommand(
            path=("check", "clear"),
            summary="A step is no longer a check; leaves no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner check clear 'Pre-release check'",),
        ),
        CliCommand(
            path=("check", "show"),
            summary="Every test a step gathers, directly or through other steps.",
            configure=step_arg,
            run=show,
            examples=("dplanner check show 'Pre-release check'",),
        ),
    ]


def lint_checks(*, covered_by: CoveredBy) -> list[LintCheck]:
    def covers_nothing(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        return [
            LintFinding(
                check="check.covers-nothing",
                subject_id=step.id,
                subject=step.title,
                message="a check with no tests behind it — link it to work that carries "
                f"tests, or `dplanner check clear '{step.title}'`",
            )
            for step in project.steps
            if read(step) and not covered_by(library, project, step.id)
        ]

    return [covers_nothing]


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step):
        # Already set is success — state-setting verbs must survive batches.
        context.report({"step": step.id, "check": True}, f"{step.title}: already a check")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(True)))
    context.report({"step": step.id, "check": True}, f"{step.title}: is a check")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not read(step):
        context.report({"step": step.id, "check": False}, f"{step.title}: not a check")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "check": False}, f"{step.title}: no longer a check")
    return 0
