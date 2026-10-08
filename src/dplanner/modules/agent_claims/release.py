"""A person's override, performed: one step handed back from the squad claim holding it, and
that step's worker stopped — the squad keeps the rest (agents.md's *A claim is a lease in
git*). Both surfaces' status verbs reach it through the ``Release`` follow-up a person's
stopped status carries; the window writes no push for it — Save carries it, as it carries
the status."""

import getpass
from collections.abc import Callable
from pathlib import Path

from dplanner.domain import claims, ledger
from dplanner.domain.questions import PERSON
from dplanner.domain.workflow import Release

# Stops one run: (project dir, run, by, why) — the supervisor's, handed in by the root.
type Stop = Callable[[Path, str, str, str], None]


def release(project_dir: Path, follow_up: Release, stop: Stop) -> bool:
    """Release ``follow_up``'s step and stop its unfinished runs under the claim; False when
    no claim held the step."""
    by = {"kind": PERSON, "name": getpass.getuser()}
    why = f"set {follow_up.why} by a person"
    try:
        claim = claims.release_step(project_dir, follow_up.step, by, why)
    except LookupError:
        return False
    if claim is None:
        return False
    for run in ledger.records(project_dir):
        if run.claim == claim.id and run.step == follow_up.step and not run.over:
            stop(project_dir, run.run, by["name"], why)
    return True
