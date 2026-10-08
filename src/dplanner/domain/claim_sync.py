"""The git half of a claim: committed and pushed, never at the cost of the person's checkout
(agents.md's *A claim is a lease in git*).

Taking, releasing and ending a claim each :func:`publish`, and so does the heartbeat at most
every thirty minutes (:func:`renew`). **A publish never rewrites the checkout it runs in**:
it commits ``claims/`` alone by pathspec — whatever else in the plan is unsaved stays the
window's to Save — under the repository's sync lock, which the window's own Save and sync
take too (``core/storage``'s ``sync_lock``), and pushes. It never fetches, rebases or
stashes: a push the remote refuses leaves the commit where it is, says the claims are not
published yet, and the window's next sync — which does rebase, with a person watching —
carries them. Ownership is decided locally from the files (``domain/claims.py``), so an
unpublished claim still holds on the machine that took it. When this machine last pushed
a claim, and that it has one waiting, are this machine's own facts, kept in
``config_dir()``.
"""

import os
from contextlib import suppress
from pathlib import Path

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic
from dplanner.core.storage.locations import find_repo_root, sync_lock
from dplanner.core.storage.provider import StorageError
from dplanner.core.storage.sparse import REMOTE_S, GitError, run_git
from dplanner.domain import claims, ledger
from dplanner.domain.model import now_stamp

PUSHED = "pushed"
UNPUBLISHED = "unpublished"  # Committed; the remote refused the push.
COMMITTED = "committed"  # Committed; there is no remote to push to.


def publish(project_dir: Path, message: str, config: Path | None = None) -> str:
    """Commit ``claims/`` and push it: :data:`PUSHED`, :data:`UNPUBLISHED`,
    :data:`COMMITTED`, or "" in a plan that is no repository. Raises ``StorageError`` only
    when the commit itself cannot be made."""
    root = find_repo_root(project_dir)
    if root is None:
        return ""
    scope = _scope(project_dir, root)
    with sync_lock(root):
        try:
            run_git(["add", "-A", "--", scope], cwd=root)
            if _staged(root, scope):
                run_git(["commit", "-q", "-m", message, "--", scope], cwd=root)
        except GitError as error:
            raise StorageError(str(error)) from error
        if "origin" not in run_git(["remote"], cwd=root).out.split():
            return COMMITTED
        try:
            branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).out.strip()
            run_git(["push", "-q", "origin", branch], cwd=root, timeout=REMOTE_S)
        except GitError:
            pushed = False
        else:
            pushed = True
    for claim in claims.records(project_dir):
        if not claim.ended:
            _mark(claim.id, config, pushed)
    return PUSHED if pushed else UNPUBLISHED


def unpublished(claim_id: str, config: Path | None = None) -> bool:
    """Whether this machine committed the claim and the remote has not taken it yet."""
    return _path(claim_id, UNPUBLISHED, config).exists()


def renew(project_dir: Path, claim_id: str = "", config: Path | None = None) -> None:
    """The heartbeat: ``claim_id`` — or, with none, every claim this machine holds in the
    project — first stands down from the steps it no longer holds, then is renewed when due,
    and published when this machine has not pushed it for ``PUSH_MINUTES``. Never raises: a
    renewal that fails is made again at the next beat."""
    here = ledger.machine_id(config)
    at = now_stamp()
    due = [
        claim
        for claim in claims.records(project_dir)
        if not claim.ended
        and (claim.id == claim_id if claim_id else claim.worker.get("machine") == here)
    ]
    changed = False
    for claim in due:
        try:
            kept = claims.stand_down(project_dir, claim.id, config)
            renewed = claims.update(project_dir, claim.id, lambda c: claims.beaten(c, at), config)
        except (LookupError, OSError):
            continue
        changed = changed or kept != claim or renewed.heartbeat == at
    if changed and any(_push_due(claim.id, at, config) for claim in due):
        with suppress(StorageError, OSError):  # The commit failed; the next beat tries again.
            publish(project_dir, f"Claims: heartbeat {at}", config)


def _staged(root: Path, scope: str) -> bool:
    try:
        run_git(["diff", "--cached", "--quiet", "--", scope], cwd=root)
    except GitError:
        return True  # `--quiet` exits 1 when there is something staged.
    return False


def _push_due(claim_id: str, at: str, config: Path | None) -> bool:
    try:
        last = _path(claim_id, PUSHED, config).read_text(encoding="utf-8").strip()
    except OSError:
        return True
    return claims.minutes_between(last, at) >= claims.PUSH_MINUTES


def _mark(claim_id: str, config: Path | None, pushed: bool) -> None:
    waiting = _path(claim_id, UNPUBLISHED, config)
    waiting.parent.mkdir(parents=True, exist_ok=True)
    if pushed:
        write_atomic(_path(claim_id, PUSHED, config), now_stamp())
        waiting.unlink(missing_ok=True)
    else:
        write_atomic(waiting, now_stamp())


def _path(claim_id: str, kind: str, config: Path | None) -> Path:
    return (config or config_dir()) / claims.CLAIMS_DIR / f"{claim_id}.{kind}"


def _scope(project_dir: Path, root: Path) -> str:
    return Path(os.path.relpath(project_dir / claims.CLAIMS_DIR, root)).as_posix()
