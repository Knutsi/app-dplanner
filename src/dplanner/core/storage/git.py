"""A git working tree: the provider that has a history.

Adapted from Writer's ``modules/gitsync/service.py``, with the Qt and the model coupling
removed. What is left is plumbing plus one policy decision worth keeping: **commits are
scoped to the workspace directory**. A workspace often sits inside a larger repository
(the application's own source, a folder of several workspaces), and a Save must never
sweep up whatever else is in the tree.

``git`` is shelled out to rather than reached through a binding. The operations here are
the ones a person would type; a library would add a build dependency and a second mental
model for no gain, and the subprocess boundary is what makes these methods honestly
blocking rather than accidentally so.

Everything here blocks. Callers run it through ``TaskRunner``.
"""

import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from dplanner.core.signals import Signal
from dplanner.core.storage.local import LocalStorage
from dplanner.core.storage.provider import Revision, StorageError

DEFAULT_BRANCH = "main"


def find_repo_root(start: Path) -> Path | None:
    """The nearest ancestor holding a ``.git``, or None when there is no repository."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def init_repo(path: Path) -> Path:
    """``git init`` at ``path`` (created if missing), returning the new repository root."""
    path = path.expanduser()
    path.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "init", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise StorageError(f"git init: {result.stderr.strip()}")
    return path


def origin_url(path: Path) -> str:
    """The ``origin`` remote URL of the repository containing ``path``, "" when absent."""
    root = find_repo_root(path.expanduser())
    if root is None:
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


class GitStorage(LocalStorage):
    """Files under a directory inside a git repository, plus that repository's history."""

    def __init__(
        self,
        root: Path,
        repo_root: Path | None = None,
        scopes: Sequence[str] | None = None,
    ) -> None:
        super().__init__(root)
        found = repo_root or find_repo_root(self._root)
        if found is None:
            raise StorageError(f"{self._root} is not inside a git repository")
        self.repo_root = found.resolve()
        # The pathspecs every commit is scoped to. One repository can hold several planned
        # directories; scoping is what keeps a Save from sweeping up the user's own source.
        if scopes is None:
            relative = self._root.relative_to(self.repo_root)
            scopes = (str(relative) if relative.parts else ".",)
        self._scopes: tuple[str, ...] = tuple(scopes)
        self._dirty = False
        self._dirty_count = 0
        self.dirty_changed: Signal[bool, int] = Signal()
        self.worktree_changed: Signal[()] = Signal()

    @property
    def scopes(self) -> tuple[str, ...]:
        """The repo-root-relative pathspecs this provider's history operations cover."""
        return self._scopes

    @property
    def label(self) -> str:
        return super().label

    # -- plumbing ------------------------------------------------------------------------------

    def _git(
        self, *args: str, check: bool = True, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(
                args=list(args), returncode=124, stdout="", stderr="timed out"
            )
        if check and result.returncode != 0:
            raise StorageError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result

    def has_origin(self) -> bool:
        """Whether this repository has an ``origin`` remote configured."""
        return self._git("remote", "get-url", "origin", check=False).returncode == 0

    def _has_ref(self, ref: str) -> bool:
        return self._git("show-ref", "--verify", "--quiet", ref, check=False).returncode == 0

    @staticmethod
    def _timestamped(prefix: str) -> str:
        return f"{prefix}: {datetime.now().astimezone().isoformat(timespec='seconds')}"

    # -- uncommitted changes -------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return self._dirty

    def dirty_file_count(self) -> int:
        return self._dirty_count

    def refresh_dirty(self) -> None:
        """Re-read the working tree against HEAD. Local only, so it is cheap enough to
        call after every autosave flush."""
        lines = self._git(
            "status", "--porcelain", "--", *self._scopes, check=False
        ).stdout.splitlines()
        dirty, count = bool(lines), len(lines)
        if dirty != self._dirty or count != self._dirty_count:
            self._dirty, self._dirty_count = dirty, count
            self.dirty_changed.emit(dirty, count)

    def diff(self) -> str:
        """The workspace's working tree against HEAD, as a unified diff.

        ``add -N`` marks untracked files as known-but-empty first, so a newly created file
        shows as a pure addition instead of vanishing from the diff — without staging its
        content or touching the working tree.
        """
        self._git("add", "-N", "--", *self._scopes, check=False)
        return self._git("diff", "HEAD", "--", *self._scopes, check=False).stdout

    # -- history -------------------------------------------------------------------------------

    def commit(self, message: str = "") -> bool:
        """Stage and commit the workspace directory only. False when nothing had changed."""
        self._git("add", "-A", "--", *self._scopes)
        staged = self._git("diff", "--cached", "--quiet", "--", *self._scopes, check=False)
        if staged.returncode == 0:
            return False
        self._git("commit", "-m", message or self._timestamped("Save"), "--", *self._scopes)
        self.refresh_dirty()
        return True

    def history(self, limit: int = 50) -> list[Revision]:
        # A unit separator between fields and a record separator between commits: commit
        # messages contain newlines, so line-splitting the log is not safe.
        result = self._git(
            "log",
            f"-{limit}",
            "--format=%H%x1f%an%x1f%aI%x1f%s%x1e",
            "--",
            *self._scopes,
            check=False,
        )
        revisions = []
        for record in result.stdout.split("\x1e"):
            fields = record.strip("\n").split("\x1f")
            if len(fields) == 4:
                revisions.append(
                    Revision(id=fields[0], author=fields[1], when=fields[2], message=fields[3])
                )
        return revisions

    # -- branches ------------------------------------------------------------------------------

    def current_branch(self) -> str:
        return self._git("branch", "--show-current", check=False).stdout.strip()

    def branches(self) -> list[str]:
        """Local and remote-tracking branches merged by name, the default branch first."""
        local = set(
            self._git(
                "for-each-ref", "refs/heads", "--format=%(refname:short)", check=False
            ).stdout.split()
        )
        remote = {
            name.removeprefix("origin/")
            for name in self._git(
                "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)", check=False
            ).stdout.split()
            if name != "origin/HEAD"
        }
        names = local | remote
        ordered = [DEFAULT_BRANCH] if DEFAULT_BRANCH in names else []
        return ordered + sorted(names - {DEFAULT_BRANCH})

    def create_branch(self, name: str) -> None:
        """Branch off the current state and switch to it.

        Pending work is committed to the branch being left first, so the new branch starts
        from a recorded state rather than carrying someone else's uncommitted edits.
        """
        self.commit(self._timestamped("Save"))
        self._git("checkout", "-b", name)

    def switch_branch(self, name: str) -> None:
        """Check out ``name``, committing pending work to the branch left behind.

        This rewrites files under the running application, so ``worktree_changed`` fires
        and the caller rebuilds the workspace. Patching a live model against an arbitrary
        checkout is not something anyone should try to get right.
        """
        if name == self.current_branch():
            return
        self.commit(self._timestamped("Save"))
        if not self._has_ref(f"refs/heads/{name}") and self._has_ref(f"refs/remotes/origin/{name}"):
            self._git("checkout", "-b", name, "--track", f"origin/{name}")
        else:
            self._git("checkout", name)
        self.refresh_dirty()
        self.worktree_changed.emit()

    def delete_branch(self, name: str, *, force: bool = False) -> None:
        """Delete a branch locally. The default branch is protected here, not just in the UI."""
        if name == DEFAULT_BRANCH:
            raise StorageError(f"{DEFAULT_BRANCH} is protected and can never be deleted")
        if name == self.current_branch():
            raise StorageError(f"{name} is checked out — switch to another branch first")
        self._git("branch", "-D" if force else "-d", name)
