"""``dplanner claim take|list|release|end`` — a squad's lease on its steps.

The coordinator takes the steps it was given before it starts any of them: ``claim take``
refuses a step another squad holds (naming the holder), and a squad word a live or parked
claim anywhere in the library answers to unless the caller's shell is that squad's own
(``$DPLANNER_CALLSIGN``) — two coordinators that chose one word would otherwise grow one
claim between them. It writes the claim — each new step
acquired now — and commits and pushes it; a push the remote refuses is left for the window's
next sync, since ownership is decided on this machine. A step whose holder has gone quiet
past its lease is taken over: the new claim names the old one, step by step, in
``supersedes``, and the old squad's workers on it are stopped. ``release`` hands one step
back, ``end`` the whole claim — the coordinator when it is done, or a person's *Clear* —
and both stop the workers they take steps from (``ownership.py``). The heartbeat between is
every ``dplanner`` run's (``claim_sync.renew``).
"""

import os
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.discovery import CALLSIGN_ENV, acting
from dplanner.cli.lookup import find_step
from dplanner.core.storage.provider import StorageError
from dplanner.domain import claim_sync, claims, ledger, questions
from dplanner.domain.claims import Claim
from dplanner.domain.model import now_stamp
from dplanner.modules.agent_claims import ownership
from dplanner.planning.kinds import key_of


def commands(*, in_agent_shell: Callable[[], bool]) -> list[CliCommand]:
    def _release(context: CliContext, args: Namespace) -> int:
        project_dir = context.store.project_dir(context.project.id)
        step = find_step(context.library, args.step, context.current)
        by = acting(args.by, in_agent_shell())
        try:
            claim = ownership.release(project_dir, step.id, by, args.why)
        except (LookupError, ValueError) as error:
            raise CliError(str(error)) from error
        if claim is None:
            raise CliError(f"no claim holds {key_of(step) or step.title}")
        said = _published(project_dir, f"Claims: {claim.callsign} releases {key_of(step)}")
        context.report(claim.to_json(), f"{key_of(step)} released from {claim.short}{said}")
        return 0

    def _end(context: CliContext, args: Namespace) -> int:
        project_dir = context.store.project_dir(context.project.id)
        by = acting(args.by, in_agent_shell())
        try:
            claim = ownership.end(
                project_dir, claims.resolve(project_dir, args.claim).id, by, args.why
            )
        except (LookupError, ValueError) as error:
            raise CliError(str(error)) from error
        said = _published(project_dir, f"Claims: {claim.callsign} ends {claim.short}")
        context.report(claim.to_json(), f"{claim.short} ended{said}")
        return 0

    return [
        CliCommand(
            path=("claim", "take"),
            summary="Take steps for your squad before starting any of them: fetched,"
            " checked, committed and pushed.",
            configure=_configure_take,
            run=_take,
            examples=("dplanner claim take S3 S4 S7 --callsign kettle",),
        ),
        CliCommand(
            path=("claim", "list"),
            summary="Which squad holds which steps, and whether each claim is live, parked"
            " or abandoned.",
            configure=_configure_list,
            run=_list,
            examples=("dplanner claim list", "dplanner claim list --all"),
        ),
        CliCommand(
            path=("claim", "release"),
            summary="Hand one step back; the squad keeps the rest.",
            configure=_configure_release,
            run=_release,
            examples=("dplanner claim release S4 --why merged",),
        ),
        CliCommand(
            path=("claim", "end"),
            summary="End a whole claim: the squad is done, or a person clears it.",
            configure=_configure_end,
            run=_end,
            examples=("dplanner claim end C-5a0b --why done",),
        ),
    ]


def _take(context: CliContext, args: Namespace) -> int:
    project = context.project
    project_dir = context.store.project_dir(project.id)
    steps = [find_step(context.library, ref, context.current) for ref in args.steps]
    keys = {step.id: key_of(step) or step.title for step in project.steps}
    squad = claims.squad_of(args.callsign)
    if not squad:
        raise CliError("name your squad with --callsign")
    with claims.acquiring(project.id):
        now = now_stamp()
        _refuse_another_squads_word(context, squad, now)
        held = claims.read_holdings(project_dir, now)
        taken = [
            f"{keys.get(step.id, step.title)} is held by {holding.claim.callsign}"
            f" ({holding.claim.short}, {holding.state})"
            for step in steps
            if (holding := held.get(step.id)) is not None
            and holding.state in claims.HOLDING
            and holding.claim.callsign != squad
        ]
        if taken:
            raise CliError("; ".join(taken))
        wanted = [step.id for step in steps]
        # An abandoned holder — another squad's, or this squad's own earlier claim — loses
        # these steps for good: the takeover names it, step by step.
        superseded = [
            {"claim": holding.claim.id, "step": step}
            for step in wanted
            if (holding := held.get(step)) is not None and holding.state == claims.ABANDONED
        ]
        claim = _written(project_dir, project.id, squad, wanted, superseded, now, args)
        said = _published(project_dir, f"Claims: {squad} takes {_listed(wanted, keys)}")
    why = f"taken over by {squad} ({claim.short})"
    for old in dict.fromkeys(entry["claim"] for entry in superseded):
        lost = [entry["step"] for entry in superseded if entry["claim"] == old]
        ownership.stop_runs(project_dir, old, lost, squad, why)
    context.report(
        claim.to_json(), f"{claim.short} {squad} holds {_listed(claim.steps, keys)}{said}"
    )
    return 0


def _refuse_another_squads_word(context: CliContext, squad: str, now: str) -> None:
    """Refuse ``squad`` when a live or parked claim in the library answers to it and the
    caller's shell is not one of that squad's."""
    running = claims.squads_holding(
        (context.store.project_dir(project.id) for project in context.library.projects), now
    )
    if squad in running and claims.squad_of(os.environ.get(CALLSIGN_ENV, "")) != squad:
        raise CliError(
            f"squad {squad} is running already ({running[squad].short}) — choose another word;"
            f" if it is your own squad, name yourself with {CALLSIGN_ENV}={claims.member(squad)}"
        )


def _written(
    project_dir: Path,
    project: str,
    squad: str,
    wanted: list[str],
    superseded: list[dict[str, str]],
    now: str,
    args: Namespace,
) -> Claim:
    """The squad's claim with ``wanted`` added — one claim per squad, so a squad that already
    holds steps here grows its live claim rather than starting a second; each new step is
    acquired now, never at the old claim's start."""
    mine = next(
        (
            c
            for c in claims.records(project_dir)
            if c.callsign == squad
            and claims.standing(c, now, {}) == claims.LIVE
            and c.worker.get("machine") == ledger.machine_id()
        ),
        None,
    )
    if mine is not None:
        try:
            return claims.update(
                project_dir, mine.id, lambda c: claims.grown(c, wanted, now, superseded)
            )
        except ValueError:
            pass  # Ended since it was read: this take starts a claim of its own.
    claim = claims.claimed(
        project,
        squad,
        wanted,
        now,
        worker={"machine": ledger.machine_id(), "host": ledger.host_name()},
        supersedes=superseded,
        lease_minutes=args.lease,
        max_park_hours=args.max_park,
    )
    claims.write(project_dir, claim)
    return claim


def _configure_take(parser: ArgumentParser) -> None:
    parser.add_argument("steps", nargs="+", help="the steps: key (S7), id or title")
    parser.add_argument(
        "--callsign", required=True, help="your squad word (kettle), or a member's (kettle-two)"
    )
    parser.add_argument(
        "--lease",
        type=int,
        default=claims.LEASE_MINUTES,
        metavar="MINUTES",
        help="how long a silent squad still holds its steps (default: %(default)s)",
    )
    parser.add_argument(
        "--max-park",
        type=int,
        default=claims.MAX_PARK_HOURS,
        metavar="HOURS",
        help="how long a squad waiting on questions still holds them (default: %(default)s)",
    )


def _configure_list(parser: ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="ended claims too")


def _list(context: CliContext, args: Namespace) -> int:
    project_dir = context.store.project_dir(context.project.id)
    now = now_stamp()
    parked = claims.parks(questions.records(project_dir))
    keys = {step.id: key_of(step) or step.title for step in context.project.steps}
    shown = [
        (claim, claims.standing(claim, now, parked))
        for claim in claims.records(project_dir)
        if args.all or not claim.ended
    ]
    lines = [
        f"{claim.short}  {claim.callsign:<10} {state:<9} {_listed(claim.steps, keys) or '-':<16}"
        f" {_ago(claim.heartbeat, now)}"
        for claim, state in shown
    ]
    context.report(
        [{**claim.to_json(), "state": state} for claim, state in shown],
        "\n".join(lines) or "no claims",
    )
    return 0


def _configure_release(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="the step: key (S7), id or title")
    parser.add_argument("--why", default="released", help="why it is handed back")
    _configure_by(parser)


def _configure_end(parser: ArgumentParser) -> None:
    parser.add_argument("claim", help="C-5a0b, or the claim's id")
    parser.add_argument("--why", default="done", help="done, released, or your own words")
    _configure_by(parser)


def _configure_by(parser: ArgumentParser) -> None:
    # Whether a person or the coordinator acts is read from the shell, never given here.
    parser.add_argument("--by", default="", help="your name or callsign (default: your user)")


def _published(project_dir: Path, message: str) -> str:
    """Commit and push what changed, and say what did not happen — the change stands on disk
    either way, and decides ownership on this machine."""
    try:
        said = claim_sync.publish(project_dir, message)
    except StorageError as error:
        return f" (not committed yet: {error})"
    if said == claim_sync.UNPUBLISHED:
        return " (committed; not published yet — the window's next sync pushes it)"
    return ""


def _listed(steps: tuple[str, ...] | list[str], keys: dict[str, str]) -> str:
    return " ".join(keys.get(step, step[:8]) for step in steps)


def _ago(stamp: str, now: str) -> str:
    minutes = claims.minutes_between(stamp, now)
    if minutes < 2:
        return "heard just now"
    if minutes < 120:
        return f"heard {round(minutes)} min ago"
    return "never heard from" if minutes == float("inf") else f"heard {round(minutes / 60)} h ago"
