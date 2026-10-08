"""A step leaving a squad, however it leaves: one function stops its worker (agents.md's *A
claim is a lease in git*).

A takeover, ``claim release``, ``claim end``, the window's *End Squad Claim* and a person's
stopped status all take steps away from a squad, and each would leave that squad's worker
running — or a parked run resumable — unless it is stopped. So every one of them ends in
:func:`stop_runs`: each unfinished headless run the squad has under the claim on those steps
is fenced, and its supervisor here is signalled, ending the turn ``stopped``; a live turn
also reads its fence within a second. A supervisor on another machine finds the fence when
the ledger reaches it — the second machine is not built yet.

A release or an end takes the step's launch lock when it is free, so a launch of the step
cannot start between the change and the fence. When a launch holds it, the launch re-reads
ownership just before it starts (``launch.start_run``) and its record already exists to be
fenced, so the release never waits on it — the window's own launch may be the holder.
"""

import getpass
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path

from dplanner.domain import claims, ledger
from dplanner.domain.claims import Claim
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import PERSON
from dplanner.domain.workflow import Release
from dplanner.modules.agent_supervisor import supervisor


def stop_runs(project_dir: Path, claim_id: str, steps: Sequence[str], by: str, why: str) -> None:
    """Fence every unfinished headless run under ``claim_id`` on ``steps`` and signal its
    supervisor on this machine: the one way a squad's worker is stopped."""
    for run in ledger.records(project_dir):
        if run.claim == claim_id and run.step in steps and run.headless and not run.over:
            supervisor.stop(project_dir, run.run, by, why)


def release(
    project_dir: Path, step: str, by: Mapping[str, str], why: str, claim_id: str = ""
) -> Claim | None:
    """Hand ``step`` back from ``claim_id`` — by default, from whichever claim holds it — and
    stop its worker. The claim as it now stands, or None when nothing held the step."""
    if not claim_id:
        holding = claims.read_holdings(project_dir, now_stamp()).get(step)
        if holding is None:
            return None
        claim_id = holding.claim.id
    found = claims.find(project_dir, claim_id)
    if found is None:
        return None
    with _launches(found.project, [step]):
        claim = claims.release_step(project_dir, step, by, why, claim_id)
        stop_runs(project_dir, claim_id, [step], by.get("name", ""), why)
    return claim


def end(project_dir: Path, claim_id: str, by: Mapping[str, str], why: str) -> Claim:
    """End the whole claim and stop every one of its workers. ``ValueError`` when it has
    already ended, ``LookupError`` when there is no such claim."""
    found = claims.find(project_dir, claim_id)
    if found is None:
        raise LookupError(f"no claim {claim_id} in this project")
    with _launches(found.project, found.steps):
        claim = claims.update(
            project_dir, claim_id, lambda c: claims.ended(c, by, why, now_stamp())
        )
        stop_runs(project_dir, claim_id, found.steps, by.get("name", ""), why)
    return claim


def released_by_status(project_dir: Path, follow_up: Release) -> bool:
    """A person's stopped status, performed: the step leaves its squad's claim and its worker
    stops. False when no claim held it. Both surfaces' status verbs reach it."""
    by = {"kind": PERSON, "name": getpass.getuser()}
    try:
        claim = release(project_dir, follow_up.step, by, f"set {follow_up.why} by a person")
    except LookupError:
        return False
    return claim is not None


@contextmanager
def _launches(project: str, steps: Sequence[str]) -> Iterator[None]:
    """The steps' launch locks that are free; one a launch holds is left to that launch."""
    with ExitStack() as held:
        for step in steps:
            try:
                held.enter_context(supervisor.launching(project, step))
            except BlockingIOError:
                continue
        yield
