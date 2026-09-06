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
        """Fast-forward from origin. True when anything arrived."""
        if not self.has_remote():
            return False
        branch = self.current_branch() or DEFAULT_BRANCH
        before = self._git("rev-parse", "HEAD", check=False).stdout.strip()
        self._git("fetch", "origin", check=False, timeout=60)
        merged = self._git("merge", "--ff-only", f"origin/{branch}", check=False)
        if merged.returncode != 0:
            # Not fast-forwardable means local and remote have diverged. Refusing is the
            # honest outcome: an automatic merge here would resolve a conflict nobody saw.
            raise StorageError(
                f"{branch} has diverged from origin — reconcile it in a terminal; "
                "your workspace is unchanged"
            )
        after = self._git("rev-parse", "HEAD", check=False).stdout.strip()
        if before == after:
            return False
        self.worktree_changed.emit()
        return True

    def push(self) -> None:
        if not self.has_remote():
            return
        branch = self.current_branch() or DEFAULT_BRANCH
        self._git("push", "-u", "origin", branch, timeout=120)

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
