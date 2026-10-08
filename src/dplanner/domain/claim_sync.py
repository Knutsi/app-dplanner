"""The git half of a claim: fetched against, committed and pushed (agents.md's *A claim is a
lease in git*).

A claim file proves nothing until it is on the remote — two machines that pulled the same
unclaimed step would each add one, and git would merge both without a conflict — so taking,
releasing and ending a claim each :func:`publish`, and a reader ranks rival claims by the
order their files arrived (:func:`push_order`). The commit covers ``claims/`` alone: whatever
else in the plan is unsaved stays the window's to Save.

The heartbeat is the other writer (:func:`renew`): written when ten minutes old, by the
coordinator's own ``dplanner`` runs and by the supervisor of a live run of the squad, and a
commit carrying nothing but a heartbeat pushed at most every thirty minutes. When this
machine last pushed a claim is this machine's own fact, kept in ``config_dir()``.
"""

import os
from contextlib import suppress
from pathlib import Path

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic
from dplanner.core.storage.locations import find_repo_root, repo_storage
from dplanner.core.storage.provider import RemoteStorage, StorageError, VersionedStorage
from dplanner.core.storage.sparse import GitError, run_git
from dplanner.domain import claims, ledger
from dplanner.domain.model import now_stamp


def refresh(project_dir: Path) -> None:
    """Bring the remote's claims in before a check. Raises ``StorageError`` when it cannot."""
    storage = _storage(project_dir)
    if isinstance(storage, RemoteStorage) and storage.has_remote():
        storage.pull()


def publish(project_dir: Path, message: str, config: Path | None = None) -> str:
    """Commit ``claims/`` and push it: "pushed", "committed" when there is no remote, or ""
    in a plan that is no repository. Raises ``StorageError`` when the push fails — the
    commit stays, and the next publish pushes it."""
    storage = _storage(project_dir)
    if not isinstance(storage, VersionedStorage):
        return ""
    storage.commit(message)
    if not (isinstance(storage, RemoteStorage) and storage.has_remote()):
        return "committed"
    storage.push()
    for claim in claims.records(project_dir):
        if claim.ended:
            continue
        _stamp(claim.id, config).parent.mkdir(parents=True, exist_ok=True)
        write_atomic(_stamp(claim.id, config), now_stamp())
    return "pushed"


def push_order(project_dir: Path) -> list[str]:
    """Claim ids in the order their files were first committed — after a fetch and a push,
    the order they reached the remote. Empty outside a repository."""
    root = find_repo_root(project_dir)
    if root is None:
        return []
    try:
        added = run_git(
            [
                "log",
                "--reverse",
                "--diff-filter=A",
                "--format=",
                "--name-only",
                "--",
                _scope(project_dir, root),
            ],
            cwd=root,
        ).out
    except GitError:
        return []
    return [Path(line).stem for line in added.splitlines() if line.endswith(".json")]


def renew(project_dir: Path, claim_id: str = "", config: Path | None = None) -> None:
    """The heartbeat: renew ``claim_id`` — or, with none, every claim this machine holds in
    the project — when it is due, and push when this machine has not pushed it for
    ``PUSH_MINUTES``. Never raises: a renewal that fails is made again at the next beat."""
    here = ledger.machine_id(config)
    at = now_stamp()
    due = [
        claim
        for claim in claims.records(project_dir)
        if not claim.ended
        and (claim.id == claim_id if claim_id else claim.worker.get("machine") == here)
    ]
    renewed = False
    for claim in due:
        try:
            changed = claims.update(project_dir, claim.id, lambda c: claims.beaten(c, at), config)
        except (LookupError, OSError):
            continue
        renewed = renewed or changed.heartbeat == at
    if renewed and any(_push_due(claim.id, at, config) for claim in due):
        with suppress(StorageError, OSError):
            publish(project_dir, f"Claims: heartbeat {at}", config)


def _push_due(claim_id: str, at: str, config: Path | None) -> bool:
    try:
        last = _stamp(claim_id, config).read_text(encoding="utf-8").strip()
    except OSError:
        return True
    return claims.minutes_between(last, at) >= claims.PUSH_MINUTES


def _stamp(claim_id: str, config: Path | None) -> Path:
    return (config or config_dir()) / claims.CLAIMS_DIR / f"{claim_id}.pushed"


def _storage(project_dir: Path) -> object:
    root = find_repo_root(project_dir)
    if root is None:
        return None
    return repo_storage(root, (_scope(project_dir, root),))


def _scope(project_dir: Path, root: Path) -> str:
    return Path(os.path.relpath(project_dir / claims.CLAIMS_DIR, root)).as_posix()
