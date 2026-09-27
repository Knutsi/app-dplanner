"""``dplanner status …`` — say where a step stands.

This is how an agent reports back: ``dplanner status set '<step>' ready-for-review`` when
its work is finished — a person or a reviewing agent looks next, and sets it
``ready-to-merge`` and ``done`` — or ``blocked`` when it cannot continue. ``status list``
is the project's board — every step grouped by status, each group in the order the work
can be done.

**An agent's run ends at ready-for-review, and the verb holds it there.** From inside an
agent's shell, ``status set <agent step> done`` on a step nobody has reviewed is refused,
naming ``ready-for-review`` — unless ``--because`` says why nothing needs reviewing, which
is kept as a ``decision`` note on the step. A person in their own terminal is never asked,
and neither is the window: the rule is about who is reporting, not about the word.
ARCHITECTURE.md's *An agent finishes at Ready for review* has the reasoning.
"""

import shlex
from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.domain.ordering import placed
from dplanner.domain.progression import DONE, READY_FOR_REVIEW, READY_TO_MERGE
from dplanner.modules.step_status.aspect import (
    MODULE_ID,
    NO_STATUS_ON_A_WAIT,
    PENDING,
    STATUSES,
    read,
    write,
)

# Somebody has looked already: an agent may take a step on from here to done.
REVIEWED = (READY_FOR_REVIEW, READY_TO_MERGE)


def commands(
    *,
    is_wait: Callable[[Step], bool],
    is_agent: Callable[[Step], bool],
    in_agent_shell: Callable[[], bool],
    note_reason: Callable[[CliContext, Step, str], str],
) -> list[CliCommand]:
    """``is_wait`` says a step is a wait, which has no status to set; ``is_agent`` that an
    agent executes it, and ``in_agent_shell`` that this command runs inside an agent CLI's
    shell — together, a done that skips review. ``note_reason`` keeps a ``--because`` as a
    decision note on the step and answers the note's id."""

    def set_status(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        if is_wait(step) and args.state != PENDING:
            raise CliError(f"{step.title!r} is a wait: {NO_STATUS_ON_A_WAIT}")
        because = (args.because or "").strip()
        if args.because is not None and args.state != DONE:
            raise CliError("--because says why a step is done without review; it goes with done")
        if (
            args.state == DONE
            and not because
            and read(step) not in REVIEWED
            and is_agent(step)
            and in_agent_shell()
        ):
            raise CliError(_review_first(step, args.step))
        _say(context, step, args.state, note_reason(context, step, because) if because else "")
        return 0

    return [
        CliCommand(
            path=("status", "set"),
            summary="Say where a step stands; setting it pending removes the file.",
            configure=_configure_set,
            run=set_status,
            examples=(
                "dplanner status set 'Read the spec' ready-for-review",
                "dplanner status set 'Read the spec' done --because 'docs only, nothing to review'",
            ),
        ),
        CliCommand(
            path=("status", "show"),
            summary="Where one step stands.",
            configure=step_arg,
            run=_show,
            examples=("dplanner status show 'Read the spec'",),
        ),
        CliCommand(
            path=("status", "clear"),
            summary="Back to pending; the step keeps the days it started and changed on.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner status clear 'Read the spec'",),
        ),
        CliCommand(
            path=("status", "list"),
            summary="A project's steps grouped by status, in working order.",
            configure=project_arg,
            run=_list,
            examples=("dplanner status list discovery",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("state", choices=STATUSES, help="where the step stands")
    parser.add_argument(
        "--because",
        metavar="REASON",
        help="with done: why the step needs no review, kept as a decision note on it",
    )


def _review_first(step: Step, needle: str) -> str:
    ref = shlex.quote(needle)
    return (
        f"{step.title!r} is an agent step, and an agent's work ends at ready-for-review:"
        f" `dplanner status set {ref} ready-for-review` — a person or a reviewing agent"
        f" sets it done. If nothing needs reviewing, say why:"
        f" `dplanner status set {ref} done --because '<reason>'`."
    )


def _say(context: CliContext, step: Step, status: str, note: str = "") -> None:
    """Write ``status``, and say so — naming the note a ``--because`` was kept as."""
    previous = step.module_data.get(MODULE_ID)
    entry = write(status, today=context.clock.today(), previous=previous)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    data = {"step": step.id, "status": status} | ({"note": note} if note else {})
    kept = f" — the reason kept as {note}" if note else ""
    context.report(data, f"{step.title}: {status}{kept}")


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    status = read(step)
    context.report({"step": step.id, "status": status}, f"{step.title}: {status}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    _say(context, find_step(context.library, args.step, context.current), PENDING)
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    order = placed(context.library, project)
    grouped = {status: [p.step for p in order if read(p.step) == status] for status in STATUSES}
    data = {
        "project": project.id,
        "statuses": {
            status: [{"id": step.id, "title": step.title} for step in steps]
            for status, steps in grouped.items()
        },
    }
    lines = []
    for status, steps in grouped.items():
        if not steps:
            continue
        lines.append(f"{status} ({len(steps)}):")
        lines.extend(f"  {step.title or 'Untitled step'}" for step in steps)
    context.report(data, "\n".join(lines) if lines else "No steps yet.")
    return 0
