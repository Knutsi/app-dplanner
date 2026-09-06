"""A git working tree with a GitHub remote: the provider that can leave the machine.

``gh`` is the only GitHub dependency, as it is in Writer, and for the same reason: it
already owns the user's authentication for pushes, so listing, cloning and creating
through it inherits a setup that works instead of asking for a second token.

Note what this class does *not* add. Pulling and pushing are ordinary ``git`` operations —
the remote being GitHub makes no difference to them — so they live here only because
``has_remote`` does. What genuinely needs ``gh`` is getting a workspace onto the machine
in the first place (:meth:`clone`) and putting a new one on the server
(:meth:`publish`), and those are classmethods: they run before any provider exists.
"""

import shutil
import subprocess
from pathlib import Path

from dplanner.core.storage.git import DEFAULT_BRANCH, GitStorage, remote_label
from dplanner.core.storage.provider import StorageError


def gh_path() -> str | None:
    """The ``gh`` executable, or None when it is not installed."""
    return shutil.which("gh")


def gh_authenticated() -> bool:
    """Whether ``gh`` can talk to GitHub right now. Advisory: pushes use plain git."""
    gh = gh_path()
    if gh is None:
        return False
    return subprocess.run([gh, "auth", "status"], capture_output=True, check=False).returncode == 0


def repository_url(checkout: Path) -> str | None:
    """The GitHub URL of the repository at ``checkout``, or None when gh cannot say.

    Silence covers every refusal the same way — gh missing, not signed in, not a
    repository, no GitHub remote — because the callers treat the answer as advisory.
    """
    if gh_path() is None:
        return None
    try:
        out = _run_gh(
            "repo", "view", "--json", "url", "--jq", ".url", cwd=checkout.expanduser(), timeout=20.0
        )
    except (StorageError, OSError):
        return None
    return out.strip() or None


def _run_gh(*args: str, cwd: Path | None = None, timeout: float = 120.0) -> str:
    gh = gh_path()
    if gh is None:
        raise StorageError("gh is not installed — GitHub workspaces need the GitHub CLI")
    try:
        result = subprocess.run(
            [gh, *args], capture_output=True, text=True, check=False, cwd=cwd, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        raise StorageError(f"gh {' '.join(args)}: timed out") from error
    if result.returncode != 0:
        raise StorageError(f"gh {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


class GitHubStorage(GitStorage):
    """A git workspace whose origin is on GitHub."""

    def has_remote(self) -> bool:
        return self._git("remote", "get-url", "origin", check=False).returncode == 0

    def remote_label(self) -> str:
        """``owner/repo`` for a GitHub origin, ``host/owner/repo`` for any other — pull and
        push are plain git, so a non-GitHub origin works; only cloning and publishing need
        gh. "" when there is no origin."""
        return remote_label(self._git("remote", "get-url", "origin", check=False).stdout.strip())

    @property
    def label(self) -> str:
        remote = self.remote_label()
        return remote or super().label

    def pull(self) -> bool:
        """Bring origin's commits in, with what is local rebased on top. True when anything
        arrived.

        A rebase rather than a fast-forward: a plan repository is written by several people
        and every *Save* is a commit, so two writers' branches diverge routinely — and two
        Saves are commits to different files far more often than a conflict. A conflict is
        aborted and refused; the tree is left as it was.
        """
        if not self.has_remote():
            return False
        branch = self.current_branch() or DEFAULT_BRANCH
        before = self._head()
        self._git("fetch", "origin", check=False, timeout=60)
        self._rebase_onto(branch)
        if before == self._head():
            return False
        self.worktree_changed.emit()
        return True

    def push(self) -> None:
        """Record the local commits on origin — after rebasing onto what arrived there
        since, so a Save from a second clone is never refused for being second."""
        if not self.has_remote():
            return
        branch = self.current_branch() or DEFAULT_BRANCH
        before = self._head()
        self._git("fetch", "origin", check=False, timeout=60)
        self._rebase_onto(branch)
        if before != self._head():
            self.worktree_changed.emit()  # Their commits are in the tree now too.
        self._git("push", "-u", "origin", branch, timeout=120)

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD", check=False).stdout.strip()

    def _rebase_onto(self, branch: str) -> None:
        """Rebase the checkout onto ``origin/<branch>`` when the two diverged. Nothing
        when origin has no such branch yet, or is behind or equal. A conflict is aborted
        — the autostash restored with it — and refused with the tree as it was."""
        if self._git("rev-parse", "--verify", f"origin/{branch}", check=False).returncode != 0:
            return
        ahead = self._git("merge-base", "--is-ancestor", f"origin/{branch}", "HEAD", check=False)
        if ahead.returncode == 0:
            return
        result = self._git("rebase", "--autostash", f"origin/{branch}", check=False, timeout=120)
        if result.returncode != 0:
            self._git("rebase", "--abort", check=False)
            raise StorageError(
                f"{branch} and origin/{branch} changed the same lines — reconcile it in a "
                "terminal; your workspace is unchanged"
            )

    # -- getting a workspace onto, and off, the machine ----------------------------------------

    @classmethod
    def clone(cls, repo: str, dest: Path) -> "GitHubStorage":
        """Clone ``owner/repo`` into ``dest`` and open it. BLOCKING."""
        dest = dest.expanduser()
        if dest.exists() and any(dest.iterdir()):
            raise StorageError(f"{dest} already exists and is not empty")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_gh("repo", "clone", repo, str(dest), timeout=300)
        return cls(dest)

    @classmethod
    def create(cls, name: str, dest: Path, *, private: bool = True) -> "GitHubStorage":
        """Create ``name`` on GitHub, empty, and clone it into ``dest``. BLOCKING.

        The Project dialog's *new code repository*: a plan that names code nobody has
        started yet. ``gh repo create --clone`` lands the clone beside where it runs, under
        the repository's own name, so it runs in ``dest``'s parent and renames after.
        """
        dest = dest.expanduser()
        if dest.exists():
            raise StorageError(f"{dest} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_gh(
            "repo",
            "create",
            name,
            "--private" if private else "--public",
            "--clone",
            cwd=dest.parent,
            timeout=300,
        )
        landed = dest.parent / name.rsplit("/", 1)[-1]
        if landed != dest:
            landed.rename(dest)
        return cls(dest)

    @classmethod
    def publish(cls, storage: GitStorage, name: str, *, private: bool = True) -> "GitHubStorage":
        """Create ``name`` on GitHub with ``storage``'s repository as its source. BLOCKING."""
        _run_gh(
            "repo",
            "create",
            name,
            "--private" if private else "--public",
            "--source",
            str(storage.repo_root),
            "--remote",
            "origin",
            "--push",
            cwd=storage.repo_root,
            timeout=300,
        )
        return cls(storage.root, repo_root=storage.repo_root)

    @staticmethod
    def list_repositories(limit: int = 100) -> list[str]:
        """The user's repositories as ``owner/repo``, newest first. BLOCKING."""
        raw = _run_gh(
            "repo",
            "list",
            "--json",
            "nameWithOwner",
            "--jq",
            ".[].nameWithOwner",
            "--limit",
            str(limit),
        )
        return [line for line in raw.splitlines() if line]
