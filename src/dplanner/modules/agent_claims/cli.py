"""``dplanner claim take|list|release|end`` — a squad's lease on its steps.

The coordinator takes the steps it was given before it starts any of them: ``claim take``
fetches, refuses a step another squad holds (naming the holder), writes the claim, commits
and pushes it — and only a pushed claim launches work. A step whose holder has gone quiet
past its lease is taken over: the new claim names the old one in ``supersedes`` and fences
the old squad's unfinished runs on it. ``release`` hands one step back, ``end`` the whole
claim — the coordinator when it is done, or a person's *Clear*. Each pushes as it goes; the
heartbeat between is every ``dplanner`` run's (``claim_sync.renew``).
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.discovery import acting
from dplanner.cli.lookup import find_step
from dplanner.core.storage.provider import StorageError
from dplanner.domain import claim_sync, claims, ledger, questions
from dplanner.domain.claims import Claim
from dplanner.domain.model import now_stamp
from dplanner.modules.agent_supervisor import supervisor
from dplanner.planning.kinds import key_of


def commands(*, in_agent_shell: Callable[[], bool]) -> list[CliCommand]:
    def _release(context: CliContext, args: Namespace) -> int:
        project_dir = context.store.project_dir(context.project.id)
        step = find_step(context.library, args.step, context.current)
        by = acting(args.by, in_agent_shell())
        try:
            claim = claims.release_step(project_dir, step.id, by, args.why)
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
            claim = claims.resolve(project_dir, args.claim)
            claim = claims.update(
                project_dir, claim.id, lambda c: claims.ended(c, by, args.why, now_stamp())
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
        try:
            claim_sync.refresh(project_dir)
        except StorageError as error:
            raise CliError(f"could not fetch the plan, so nothing is claimed: {error}") from error
        now = now_stamp()
        held = claims.read_holdings(project_dir, now, claim_sync.push_order(project_dir))
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
        added = [
            step
            for step in wanted
            if (holding := held.get(step)) is None
            or holding.state not in claims.HOLDING
            or holding.claim.callsign != squad
        ]
        abandoned = {
            holding.claim.id
            for step in wanted
            if (holding := held.get(step)) is not None and holding.state == claims.ABANDONED
        }
        claim = _written(project_dir, project.id, squad, wanted, abandoned, now, args)
        try:
            claim_sync.publish(project_dir, f"Claims: {squad} takes {_listed(wanted, keys)}")
        except StorageError as error:
            for step in added:
                claims.release_step(project_dir, step, _squad(squad), "not pushed", claim.id)
            raise CliError(f"the claim could not be pushed, so it was let go: {error}") from error
        lost = _lost_race(project_dir, claim, added)
        claim = claims.find(project_dir, claim.id) or claim
    for run in ledger.records(project_dir):
        if run.claim in abandoned and run.step in wanted and not run.over and not run.fence:
            supervisor.fence(project_dir, run.run, squad, f"taken over by {squad} ({claim.short})")
    lines = [f"{claim.short} {squad} holds {_listed(claim.steps, keys)}"]
    lines += [f"{keys.get(step, step)}: {why}" for step, why in lost.items()]
    context.report({**claim.to_json(), "lost": lost}, "\n".join(lines))
    return 0


def _written(
    project_dir: Path,
    project: str,
    squad: str,
    wanted: list[str],
    abandoned: set[str],
    now: str,
    args: Namespace,
) -> Claim:
    """The squad's claim with ``wanted`` added — one claim per squad, so a squad that already
    holds steps here grows its claim rather than starting a second."""
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
    if mine is None:
        claim = claims.claimed(
            project,
            squad,
            wanted,
            now,
            worker={"machine": ledger.machine_id(), "host": ledger.host_name()},
            supersedes=sorted(abandoned),
            lease_minutes=args.lease,
            max_park_hours=args.max_park,
        )
        claims.write(project_dir, claim)
        return claim

    def grown(claim: Claim) -> Claim:
        return replace(
            claim,
            steps=tuple(dict.fromkeys((*claim.steps, *wanted))),
            supersedes=tuple(dict.fromkeys((*claim.supersedes, *sorted(abandoned)))),
            heartbeat=now,
        )

    return claims.update(project_dir, mine.id, grown)


def _lost_race(project_dir: Path, claim: Claim, wanted: list[str]) -> dict[str, str]:
    """The steps a rival pushed first, now that both are on the remote: ours stands down
    from them — the order the claims arrived decides, never a clock."""
    held = claims.read_holdings(project_dir, now_stamp(), claim_sync.push_order(project_dir))
    lost: dict[str, str] = {}
    for step in wanted:
        holder = held.get(step)
        if holder is not None and holder.claim.id != claim.id and holder.state in claims.HOLDING:
            why = f"taken first by {holder.claim.callsign} ({holder.claim.short})"
            claims.release_step(project_dir, step, _squad(claim.callsign), why, claim.id)
            lost[step] = why
    if lost:
        _published(project_dir, f"Claims: {claim.callsign} stands down")
    return lost


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
    """Push what changed; a failure is said, not raised — the change stands on disk, and the
    next heartbeat pushes it."""
    try:
        claim_sync.publish(project_dir, message)
    except StorageError as error:
        return f" (not pushed yet: {error})"
    return ""


def _squad(callsign: str) -> dict[str, str]:
    return {"kind": "coordinator", "name": callsign}


def _listed(steps: tuple[str, ...] | list[str], keys: dict[str, str]) -> str:
    return " ".join(keys.get(step, step[:8]) for step in steps)


def _ago(stamp: str, now: str) -> str:
    minutes = claims.minutes_between(stamp, now)
    if minutes < 2:
        return "heard just now"
    if minutes < 120:
        return f"heard {round(minutes)} min ago"
    return "never heard from" if minutes == float("inf") else f"heard {round(minutes / 60)} h ago"
