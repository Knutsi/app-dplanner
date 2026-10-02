"""The storage contract: one required protocol, two capabilities.

Every provider gives the application a **local working directory** it can read and write
with ordinary file operations. That is a deliberate limit, not an oversight: it keeps the
repository layer simple (it opens files), it keeps a workspace inspectable in a file
browser, and it is what every backend worth having — a plain folder, a git clone, a synced
directory — can honestly offer. A provider that could only speak over a network would have
to fake a directory anyway.

What differs between providers is *history*, and history is expressed as capabilities
rather than as optional methods that return ``None``:

- everything satisfies :class:`StorageProvider`;
- a backend with commits also satisfies :class:`VersionedStorage`;
- a backend with a remote also satisfies :class:`RemoteStorage`.

Both are ``@runtime_checkable``, so a feature asks ``isinstance(storage, VersionedStorage)``
and degrades honestly — the sync module registers no Save action at all against a plain
folder, rather than showing one that quietly does nothing. This is the same shape as
``PersistsModuleData`` in :mod:`dplanner.framework.module`.

**Every method that touches the network or spawns a process blocks.** Callers run them
through ``TaskRunner`` on a worker thread, exactly as they do ``LLMProvider.complete``.
The signals here are the Qt-free :class:`dplanner.core.signals.Signal`, so this layer stays
testable with plain pytest; the framework re-emits them on the GUI thread.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from dplanner.core.signals import Signal

# Workspace-relative, always posix, always forward slashes — the same string on every
# platform, which matters because these paths end up in commit pathspecs and in JSON.
type StoragePath = PurePosixPath | str


class StorageError(RuntimeError):
    """A storage operation failed. The message is shown to the user as-is."""


class DivergedError(StorageError):
    """The checkout and its remote changed the same lines, so neither could be laid on the
    other. The local commits are intact; what failed is bringing the two together.

    Typed, and carrying the repository, because the answer is not "try again": somebody has
    to reconcile ``branch`` with ``origin/<branch>`` in ``repo_root``, and a window that
    knows which repository can offer to send an agent there."""

    def __init__(self, repo_root: Path, branch: str) -> None:
        super().__init__(f"{branch} and origin/{branch} changed the same lines")
        self.repo_root = repo_root
        self.branch = branch


@dataclass(frozen=True)
class Revision:
    """One entry of a workspace's history."""

    id: str  # Backend-specific: a git sha, a snapshot id.
    message: str
    author: str
    when: str  # ISO-8601, so it sorts and prints without a date library.


class StorageProvider(Protocol):
    """A workspace's bytes. The only thing that knows where data physically lives."""

    @property
    def root(self) -> Path:
        """The local working directory. Everything below is relative to it."""
        ...

    @property
    def label(self) -> str:
        """How this workspace is named to the user: a path, or ``owner/repo``."""
        ...

    def exists(self, path: StoragePath) -> bool: ...

    def read_text(self, path: StoragePath) -> str | None:
        """The file's contents, or None when it does not exist.

        None rather than an exception because *absent* is a normal, meaningful state in a
        file-backed format: an unwritten optional file encodes its default.
        """
        ...

    def read_bytes(self, path: StoragePath) -> bytes | None: ...

    def write_text(self, path: StoragePath, text: str) -> None:
        """Write ``text``, creating parent directories. Atomic: a crash never truncates."""
        ...

    def write_bytes(self, path: StoragePath, data: bytes) -> None: ...

    def delete(self, path: StoragePath) -> None:
        """Remove a file, or an empty directory. Missing is not an error."""
        ...

    def list_dir(self, path: StoragePath = "") -> list[str]:
        """Names directly inside ``path``, sorted. Empty when it does not exist."""
        ...

    def is_dir(self, path: StoragePath) -> bool: ...

    def make_dir(self, path: StoragePath) -> None: ...


@runtime_checkable
class VersionedStorage(Protocol):
    """Capability: this workspace has a history, so *Save* can mean something.

    ``dirty_changed`` is what the window's unsaved-changes indicator listens to.
    ``worktree_changed`` is the inbound path — the one case where storage changes files
    under a running application (a branch switch, a pull) and the workspace must be rebuilt
    rather than patched.
    """

    dirty_changed: Signal[bool, int]  # (has uncommitted changes, changed file count)
    worktree_changed: Signal[()]  # Files were rewritten underneath us: reload.

    def is_dirty(self) -> bool: ...

    def dirty_file_count(self) -> int:
        """How many files differ from the last recorded version. Cached, like is_dirty."""
        ...

    def refresh_dirty(self) -> None:
        """Re-check the working tree; emits ``dirty_changed`` only on a real change."""
        ...

    def diff(self) -> str:
        """Uncommitted changes as a unified diff, for the user to review before saving."""
        ...

    def commit(self, message: str, also: Sequence[str] = ()) -> bool:
        """Record the current state. False when there was nothing to record. BLOCKING.

        ``also`` names extra root-relative paths to record in the same version, beside the
        workspace the provider is scoped to — the repository's project index beside the plan.
        A provider without scopes may ignore it.
        """
        ...

    def history(self, limit: int = 50) -> list[Revision]:
        """Newest first. BLOCKING."""
        ...

    def current_branch(self) -> str:
        """The active line of work; "" when the concept does not apply right now."""
        ...

    def branches(self) -> list[str]:
        """Every line of work, the default one first. BLOCKING."""
        ...

    def create_branch(self, name: str) -> None:
        """Branch off the current state and switch to it. BLOCKING."""
        ...

    def switch_branch(self, name: str) -> None:
        """Check out ``name``. Rewrites the working tree — emits ``worktree_changed``.

        BLOCKING.
        """
        ...


@runtime_checkable
class RemoteStorage(Protocol):
    """Capability: this workspace has somewhere else to be. Implies :class:`VersionedStorage`."""

    def has_remote(self) -> bool: ...

    def remote_label(self) -> str:
        """The remote as the user knows it, e.g. ``Knutsi/plans``. "" when there is none."""
        ...

    def pull(self) -> bool:
        """Bring in remote work. True when anything arrived. Emits ``worktree_changed``
        if it did. BLOCKING."""
        ...

    def push(self) -> None:
        """Send local history to the remote. BLOCKING."""
        ...
