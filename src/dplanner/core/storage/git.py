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

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
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


def main_checkout(root: Path) -> Path:
    """The main checkout of the repository ``root`` belongs to: itself, unless it is a
    linked worktree, whose ``.git`` is a *file* naming ``<main>/.git/worktrees/<name>``.

    Two things read this: the CLI resolving a project from inside an agent's worktree,
    and the skill's caution against an editable install into one.
    """
    gitfile = root / ".git"
    if not gitfile.is_file():
        return root
    content = gitfile.read_text().strip()
    if not content.startswith("gitdir:"):
        return root
    gitdir = Path(content.removeprefix("gitdir:").strip())
    if gitdir.parent.name == "worktrees" and gitdir.parents[1].name == ".git":
        return gitdir.parents[2]
    return root


def init_repo(path: Path) -> Path:
    """``git init`` at ``path`` (created if missing), returning the new repository root."""
    path = path.expanduser()
    path.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "init", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise StorageError(f"git init: {result.stderr.strip()}")
    return path


# origin_url's answers, keyed by repository root, stamped with the config file they came
# from. An action state asks this on every context change, and a subprocess per ask was
# most of a gesture's pause on macOS; a stat is what it costs now.
_ORIGINS: dict[Path, tuple[int, str]] = {}


def origin_url(path: Path) -> str:
    """The ``origin`` remote URL of the repository containing ``path``, "" when absent.

    Memoised on the mtime of the main checkout's ``.git/config`` — the file ``git remote``
    reads and rewrites (by lock-and-rename, so the stamp always moves), for every linked
    worktree too. ``extensions.worktreeConfig`` is not handled; nothing here sets it.
    """
    root = find_repo_root(path.expanduser())
    if root is None:
        return ""
    config = main_checkout(root) / ".git" / "config"
    stamp = config.stat().st_mtime_ns if config.is_file() else -1
    hit = _ORIGINS.get(root)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    url = result.stdout.strip() if result.returncode == 0 else ""
    _ORIGINS[root] = (stamp, url)
    return url


_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://")
# git's scp-like form, `user@host:path`. Two characters of host at least, so a Windows drive
# letter (`C:\code`) reads as the path it is.
_SCP_LIKE = re.compile(r"^(?:[^@/\\]+@)?(?P<host>[^:/\\]{2,}):(?P<path>[^/\\].*)$")


def _split_remote(url: str) -> tuple[str, str] | None:
    """``(host, path)`` of a remote URL in any of git's spellings; None for a local path."""
    scheme = _SCHEME.match(url)
    if scheme is not None:
        if scheme.group("scheme").lower() == "file":
            return None
        host, _, path = url[scheme.end() :].partition("/")
        host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    else:
        scp = _SCP_LIKE.match(url)
        if scp is None:
            return None
        host, path = scp.group("host"), scp.group("path")
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return host, path.rstrip("/")


def _local_path(text: str) -> str:
    scheme = _SCHEME.match(text)
    if scheme is not None:  # file://…
        text = text[scheme.end() :]
    return str(Path(text).expanduser().resolve())


def canonical_remote(url: str) -> str:
    """One spelling for a remote, so two clones can be told to be the same repository.

    ``https://github.com/Acme/widget.git``, ``git@github.com:acme/widget`` and
    ``ssh://git@github.com:22/acme/widget/`` all become ``github.com/acme/widget`` —
    scheme, user, port, ``.git`` and trailing slashes dropped, the whole lowercased, since
    a host treats its names case-insensitively. A local path — a bare repository on disk,
    a ``file://`` URL — becomes its resolved path, case kept. "" stays "".
    """
    text = url.strip()
    if not text:
        return ""
    split = _split_remote(text)
    if split is None:
        return _local_path(text)
    host, path = split
    return f"{host}/{path}".lower().rstrip("/")


def remote_label(url: str) -> str:
    """How a remote is named to a person: ``Acme/Widget`` for a GitHub repository as its
    owner spelt it, ``host/owner/repo`` for any other host, the path for a local one."""
    text = url.strip()
    if not text:
        return ""
    split = _split_remote(text)
    if split is None:
        return _local_path(text)
    host, path = split
    return path if host.lower() == "github.com" else f"{host.lower()}/{path}"


@dataclass(frozen=True)
class Activity:
    """What git says about one directory: who touched it last and when, everyone who has,
    and how many commits — over the last ``limit`` commits the reader looked at."""

    last_author: str
    last_when: str  # ISO-8601; "" when nothing has been committed there.
    authors: tuple[str, ...]  # Most recent first, each once.
    commits: int


def activity(root: Path, path: str = "", limit: int = 30) -> Activity:
    """Who has been working under ``path`` of the repository at ``root``, from its log.

    ``path`` is repository-relative ("" for the whole tree). Only the last ``limit``
    commits are read — enough to say who is on it and when it last moved, without walking
    a long history on every look. A directory with no commits, or no repository at all,
    answers an empty activity rather than an error.
    """
    args = ["git", "-C", str(root), "log", f"-{limit}", "--format=%an%x1f%aI"]
    if path and path != ".":
        args += ["--", path]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    lines = [line for line in result.stdout.splitlines() if line] if result.returncode == 0 else []
    if not lines:
        return Activity("", "", (), 0)
    author, _, when = lines[0].partition("\x1f")
    authors = tuple(dict.fromkeys(line.partition("\x1f")[0] for line in lines))
    return Activity(author, when, authors, len(lines))


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

    def commit(self, message: str = "", also: Sequence[str] = ()) -> bool:
        """Stage and commit the workspace directory — plus ``also``, repo-root-relative
        paths recorded in the same version. False when nothing had changed.

        A scope nothing matches — a directory that was never tracked and is gone now — is
        left out rather than failing the whole commit on git's *did not match any files*:
        moving a plan out of a repository commits its removal, which is only a change
        where the plan was tracked.

        ``also`` is for what is written beside the plan on purpose (the reports directory)
        and is deliberately not part of ``scopes``: the dirty count and the review diff
        stay about the plan, and a publication that failed to write never reads as
        unsaved work.
        """
        scopes = [scope for scope in (*self._scopes, *also) if self._matches(scope)]
        if not scopes:
            return False
        self._git("add", "-A", "--", *scopes)
        staged = self._git("diff", "--cached", "--quiet", "--", *scopes, check=False)
        if staged.returncode == 0:
            return False
        self._git("commit", "-m", message or self._timestamped("Save"), "--", *scopes)
        self.refresh_dirty()
        return True

    def _matches(self, scope: str) -> bool:
        """Whether a pathspec names anything: present in the tree, or known to the index."""
        if (self.repo_root / scope).exists():
            return True
        return bool(self._git("ls-files", "--", scope, check=False).stdout.strip())

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
        and the caller brings its model up to date with the tree — by reading what changed
        into it, or by rebuilding when it cannot.
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
