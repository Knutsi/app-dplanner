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

**A status that says nobody is working the step ends the claim on it.** An agent says it is
at work with ``dplanner agent-work`` (``domain/at_work.py``), and the window stands a banner
for it; ``ready-for-review``, ``ready-to-merge``, ``done`` and ``blocked`` each say the work
has stopped, so setting one ends that step's claim in the same run, whoever sets it. The
banner an agent forgot to take down was the common case, and the one verb every finishing
agent is sure to run is this one.

Both rules are ``workflows.py``'s, and the window's Status verbs call the same functions:
this file only reads the arguments, names the actor and says what happened.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.model import Step
from dplanner.domain.ordering import placed
from dplanner.domain.workflow import Actor, AgentRun, EndClaim, Person
from dplanner.modules.step_status.workflows import Kept, Performed, StatusWorkflow, perform
from dplanner.planning.status import Status, stored, word


def commands(
    *,
    workflow: StatusWorkflow,
    in_agent_shell: Callable[[], bool],
    end_claim: Callable[[EndClaim], bool],
) -> list[CliCommand]:
    """``in_agent_shell`` says this command runs inside an agent CLI's shell — the actor is
    then an agent run; ``end_claim`` ends an agent's at-work claim and answers whether one
    stood."""

    def actor() -> Actor:
        return AgentRun() if in_agent_shell() else Person()

    def set_status(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        state = Status(args.state)
        _set(context, step, state, actor(), (args.because or "").strip())
        return 0

    def clear(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        _set(context, step, Status.PENDING, actor())
        return 0

    def _set(
        context: CliContext, step: Step, status: Status, who: Actor, because: str = ""
    ) -> None:
        """Write ``status`` through the workflow, and say so once it is written — naming the
        note a ``--because`` was kept as, or the one already there that it did not replace,
        and the agent's claim it ended."""

        def say(kept: Kept | None, done: Performed) -> None:
            data = (
                {"step": step.id, "status": status.value}
                | ({"note": kept.note} if kept else {})
                | ({"claim_ended": True} if done.ended else {})
            )
            reason = (
                (
                    f" — the reason kept as {kept.note}"
                    if kept.added
                    else f" — a reason is already recorded as {kept.note}"
                )
                if kept
                else ""
            )
            released = " — no agent at work on it now" if done.ended else ""
            context.report(data, f"{step.title}: {status.value}{reason}{released}")

        write_status(
            context, workflow, end_claim, step, status, actor=who, because=because, then=say
        )

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
            run=clear,
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


def write_status(
    context: CliContext,
    workflow: StatusWorkflow,
    end_claim: Callable[[EndClaim], bool],
    step: Step,
    status: Status,
    *,
    actor: Actor,
    because: str = "",
    then: Callable[[Kept | None, Performed], None] = lambda _kept, _done: None,
) -> None:
    """Set a status the way every verb does: refused as one line, applied now, and its
    follow-ups owed to after the invocation is written — ``then`` hears what came of them.
    A claim that could not be ended is refused once the rest is done, saying the status
    stands."""
    if why := workflow.refusal([step], status, actor, because):
        raise CliError(why)
    change, kept = workflow.set_status(
        context.library, step, status, actor=actor, today=context.clock.today(), because=because
    )
    if change.command is not None:
        context.apply(change.command)

    def settle() -> None:
        done = perform(change.follow_ups, end_claim)
        then(kept, done)
        if done.failed:
            raise CliError(
                "; ".join(
                    f"{step.title}: {status.value} is written, but the agent's claim on it"
                    f" could not be ended ({why}) — `dplanner agent-work end` ends it"
                    for _claim, why in done.failed
                )
            )

    context.after_flush.append(settle)


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "state", choices=[status.value for status in Status], help="where the step stands"
    )
    parser.add_argument(
        "--because",
        metavar="REASON",
        help="with done: why the step needs no review, kept as a decision note on it",
    )


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    status = word(stored(step))
    context.report({"step": step.id, "status": status}, f"{step.title}: {status}")
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    order = placed(context.library, project)
    grouped = {status: [p.step for p in order if stored(p.step) is status] for status in Status}
    data = {
        "project": project.id,
        "statuses": {
            status.value: [{"id": step.id, "title": step.title} for step in steps]
            for status, steps in grouped.items()
        },
    }
    lines = []
    for status, steps in grouped.items():
        if not steps:
            continue
        lines.append(f"{status.value} ({len(steps)}):")
        lines.extend(f"  {step.title or 'Untitled step'}" for step in steps)
    context.report(data, "\n".join(lines) if lines else "No steps yet.")
    return 0
