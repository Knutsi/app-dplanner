"""``dplanner agent-work …`` — the agent's own account of what it is doing, right now.

The verbs an agent runs so a developer with a window open can see that somebody else is
editing the plan, what they are doing, and how long ago they were last heard from:

    dplanner agent-work start 'Cutting the graph from the payments spec' --of 12
    dplanner agent-work set 'Linking the steps' --done 8
    dplanner agent-work end

``start`` begins a claim and ``set`` moves it along — and ``set`` begins one too, because
an agent that reports progress without having said it started is telling us the same
thing, and refusing it would cost the developer the very warning it came with. ``--step``
makes the claim that step's, so several agents on one plan are several claims and each
says which work it is on; without one the claim is on the plan as a whole.

**Nothing here proves an agent is alive, and nothing tries.** The claim's last sign of life
is renewed by *every* ``dplanner`` run (``cli/main.py``), so an agent that is working
renews it without thinking about it; an agent that is thinking for twenty minutes is quiet
and says so in the words. ``domain/at_work.py`` has the reasoning.

This is the CLI's alone. The window reads claims and can clear one a dead agent left, and
there is no window verb that makes one: a claim is the other writer's statement about
itself, and a window claiming to be an agent would be the one thing this cannot survive.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from typing import Any

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_step
from dplanner.domain.at_work import AtWork, AtWorkBoard, claim_words, heard_words, is_fresh
from dplanner.domain.model import Project, Step

DOING_HELP = "one line about what you are doing, as the developer should read it"
STEP_HELP = "the step being worked (key, id or title); without one the claim is the plan's"

# How a step is printed — the composition root's one key rule, handed down like every
# other surface's. None falls back to the step's title.
KeyOf = Callable[[Step], str]


def commands(*, board: AtWorkBoard, key_of: KeyOf | None = None) -> list[CliCommand]:
    """The verbs over one board, both supplied by the composition root: the board because
    no feature module names ``config_dir()``, the key rule because every surface prints a
    step the same way."""

    def start(context: CliContext, args: Namespace) -> int:
        project, step = _target(context, args)
        claim = board.start(project.id, step.id if step else "", args.doing, args.of)
        return _say(context, claim, project.title, _key(step, key_of))

    def update(context: CliContext, args: Namespace) -> int:
        project, step = _target(context, args)
        claim = board.set(project.id, step.id if step else "", args.doing, args.done, args.of)
        return _say(context, claim, project.title, _key(step, key_of))

    def end(context: CliContext, args: Namespace) -> int:
        project, step = _target(context, args)
        ended = board.end(project.id, step.id if step else "")
        key = _key(step, key_of)
        where = f"{project.title} · {key}" if key else project.title
        context.report(
            {"project": project.id, "step": step.id if step else "", "ended": ended},
            f"{where}: no agent at work" + ("" if ended else " (nothing was claimed)"),
        )
        return 0

    def show(context: CliContext, args: Namespace) -> int:
        claims = board.claims() if args.all else board.claims(context.project.id)
        data = [_json(claim) for claim in claims]
        text = "\n".join(_row(context, claim, key_of) for claim in claims)
        context.report(data, text or "no agent at work")
        return 0

    return [
        CliCommand(
            path=("agent-work", "start"),
            summary="Say an agent is now at work on this project, and on what.",
            configure=_configure_start,
            run=start,
            examples=(
                "dplanner agent-work start 'Cutting the graph from the payments spec' --of 12",
                "dplanner agent-work start 'Building the modal' --step S7",
            ),
        ),
        CliCommand(
            path=("agent-work", "set"),
            summary="Update what the agent at work is doing, and how far it has come.",
            configure=_configure_set,
            run=update,
            examples=(
                "dplanner agent-work set 'Linking the steps' --done 8",
                "dplanner agent-work set --done 9 --step S7",
            ),
        ),
        CliCommand(
            path=("agent-work", "end"),
            summary="The agent has stopped; the window stops saying it is at work.",
            configure=_configure_step,
            run=end,
            examples=("dplanner agent-work end", "dplanner agent-work end --step S7"),
        ),
        CliCommand(
            path=("agent-work", "show"),
            summary="Who is at work on this project right now, and when each was last heard.",
            configure=_configure_show,
            run=show,
            examples=("dplanner agent-work show", "dplanner agent-work show --all"),
        ),
    ]


def _configure_step(parser: ArgumentParser) -> None:
    parser.add_argument("--step", default="", help=STEP_HELP)


def _configure_start(parser: ArgumentParser) -> None:
    parser.add_argument("doing", nargs="?", default="", help=DOING_HELP)
    _configure_step(parser)
    parser.add_argument(
        "--of", type=int, default=0, help="how many things there are to do, when you can count"
    )


def _configure_set(parser: ArgumentParser) -> None:
    parser.add_argument("doing", nargs="?", default=None, help=DOING_HELP)
    _configure_step(parser)
    parser.add_argument("--done", type=int, default=None, help="how many of them are done")
    parser.add_argument("--of", type=int, default=None, help="how many there are in all")


def _configure_show(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--all", action="store_true", help="every project on this machine, not just this one"
    )


def _target(context: CliContext, args: Namespace) -> tuple[Project, Step | None]:
    """The project the claim is on, and the step when one was named.

    A step names its own project, so ``--step`` naming a step of another project is not a
    mistake to re-scope silently — the claim goes where the step is.
    """
    if not args.step:
        return context.project, None
    step = find_step(context.library, args.step, context.current)
    return context.library.project_of(step.id), step


def _say(context: CliContext, claim: AtWork, where: str, key: str) -> int:
    context.report(_json(claim), claim_words(claim, where, key))
    return 0


def _row(context: CliContext, claim: AtWork, key_of: KeyOf | None) -> str:
    """One claim as ``show`` prints it — including claims on projects this library does
    not list, which ``--all`` deliberately reaches: another window's agent is still an
    agent running on this machine."""
    library = context.library
    has = library.has(claim.project)
    where = str(getattr(library.node(claim.project), "title", "")) if has else ""
    step: Step | None = None
    if claim.step:
        try:
            step = library.step(claim.step)
        except KeyError:
            step = None
    return claim_words(claim, where, _key(step, key_of))


def _key(step: Step | None, key_of: KeyOf | None) -> str:
    if step is None:
        return ""
    return (key_of(step) if key_of is not None else "") or step.title


def _json(claim: AtWork) -> dict[str, Any]:
    """The record plus the two things a reader would otherwise have to derive: whether it
    still reads as at work, and the same words the window shows."""
    return {**claim.to_json(), "at_work": is_fresh(claim), "heard": heard_words(claim)}
