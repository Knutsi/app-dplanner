"""A step leaving a squad, however it leaves: one function stops its worker (agents.md's *A
claim is a lease in git*).

A takeover, ``claim release``, ``claim end``, the window's *End Squad Claim*, a person's
stopped status and a stopped playbook all take steps away from a squad, and each would leave
that squad's worker running — or a parked run resumable — unless it is stopped. So every
one of them ends in :func:`stop_runs`: each unfinished headless run the squad has under the
claim on those steps is fenced, and its supervisor here is signalled, ending the turn
``stopped``; a live turn also reads its fence within a second. A supervisor on another
machine finds the fence when the ledger reaches it — the second machine is not built yet.
The step's playbook pass under the claim is halted with them (a :data:`Halt`, the engine's,
handed in): a stage done or a gate waiting has no run to fence, and the gate answered
afterwards would launch the next stage as nobody's.

A release or an end takes the steps' launch locks when they are free, around the fencing.
Either way a launch of the step cannot slip through: one that re-reads ownership just before
it starts (``launch.start_run``) after the change is refused, and one that started before it
already has a record to fence — so the release never waits on a launch, which may be the
window's own.
"""

import getpass
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path

from dplanner.domain import claims, ledger
from dplanner.domain.claims import Claim
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import PERSON
from dplanner.domain.workflow import Release
from dplanner.modules.agent_supervisor import supervisor

# Halt the step's playbook pass when it is the claim's: (project_dir, step, claim, by, why).
Halt = Callable[[Path, str, str, str, str], object]


def stop_runs(
    project_dir: Path, claim_id: str, steps: Sequence[str], by: str, why: str, halt: Halt
) -> None:
    """Halt the playbook pass ``claim_id`` has on each of ``steps``, fence every unfinished
    headless run under it there and signal its supervisor on this machine: the one way a
    squad's worker is stopped."""
    for step in steps:
        halt(project_dir, step, claim_id, by, why)
    for run in ledger.records(project_dir):
        if run.claim == claim_id and run.step in steps and run.headless and not run.over:
            supervisor.stop(project_dir, run.run, by, why)


def release(
    project_dir: Path,
    step: str,
    by: Mapping[str, str],
    why: str,
    halt: Halt,
    claim_id: str = "",
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
        stop_runs(project_dir, claim_id, [step], by.get("name", ""), why, halt)
    return claim


def end(project_dir: Path, claim_id: str, by: Mapping[str, str], why: str, halt: Halt) -> Claim:
    """End the whole claim and stop every one of its workers — on exactly the steps it held
    when it ended, read under the claim's lock, so a step another take added a moment before
    is stopped too, and a take a moment after cannot grow the ended claim (``claims.grown``
    refuses it). ``ValueError`` when it has already ended, ``LookupError`` when there is no
    such claim."""
    held: list[str] = []

    def ending(claim: Claim) -> Claim:
        held[:] = claim.steps
        return claims.ended(claim, by, why, now_stamp())

    claim = claims.update(project_dir, claim_id, ending)
    with _launches(claim.project, held):
        stop_runs(project_dir, claim_id, held, by.get("name", ""), why, halt)
    return claim


def released_by_person(project_dir: Path, follow_up: Release, halt: Halt) -> bool:
    """A person's override, performed — a stopped status, a stopped playbook: the step leaves
    its squad's claim and its worker stops. False when no claim held it."""
    by = {"kind": PERSON, "name": getpass.getuser()}
    try:
        claim = release(project_dir, follow_up.step, by, f"{follow_up.why} by a person", halt)
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
