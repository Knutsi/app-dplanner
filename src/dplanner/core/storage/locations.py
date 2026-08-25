"""Choosing a provider: the one place a concrete storage class is named.

A workspace is identified by a short string the user can type, keep in a settings file, or
pass on the command line:

===========================  ===============================================================
``~/Plans/roadmap``          a directory — the richest provider it can support is used
``file:~/Plans/roadmap``     the same directory, forced to a plain folder with no history
``git:~/Plans/roadmap``      the same directory, required to be inside a git repository
``github:Knutsi/plans``      a GitHub repository, cloned on first open
===========================  ===============================================================

The bare form is the interesting one. ``open_storage`` looks at what is actually there and
returns the most capable provider that fits: a git checkout with an origin becomes a
:class:`GitHubStorage`, a git checkout without one a :class:`GitStorage`, and anything else
a :class:`LocalStorage`. The application does not branch on the answer — it asks the
provider what it can do through the capability protocols, which is why the same build runs
against all three.

An explicit scheme overrides the detection, so ``file:`` on a git checkout is a supported
way to say *don't offer me version control today*.
"""

from dataclasses import dataclass
from pathlib import Path

from dplanner.core.storage.git import GitStorage, find_repo_root
from dplanner.core.storage.github import GitHubStorage
from dplanner.core.storage.local import LocalStorage
from dplanner.core.storage.provider import StorageError, StorageProvider

_SCHEMES = ("file", "git", "github")


@dataclass(frozen=True)
class StorageLocation:
    """A parsed workspace reference. ``scheme`` is "" when the string named a bare path."""

    scheme: str
    target: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.target}" if self.scheme else self.target

    @property
    def path(self) -> Path | None:
        """The local directory this names, or None for a location that must be cloned."""
        if self.scheme == "github":
            return None
        return Path(self.target).expanduser()


def parse_location(raw: str) -> StorageLocation:
    """Read a workspace reference. Raises ``StorageError`` on an unknown scheme."""
    text = raw.strip()
    if not text:
        raise StorageError("no workspace given")
    head, _, tail = text.partition(":")
    # A bare Windows-style drive letter or an absolute path with a colon in it is a path,
    # not a scheme — only the schemes we actually define are treated as such.
    if tail and head in _SCHEMES:
        return StorageLocation(scheme=head, target=tail)
    return StorageLocation(scheme="", target=text)


def describe_location(location: StorageLocation) -> str:
    """How to name this workspace before it has been opened (the Recent menu, errors)."""
    if location.scheme == "github":
        return f"GitHub · {location.target}"
    path = location.path
    assert path is not None  # Only "github" has no local path.
    home = Path.home()
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)


def clone_target(location: StorageLocation, into: Path) -> Path:
    """Where a ``github:`` location lands locally: ``into`` plus the repository name."""
    return into.expanduser() / location.target.split("/")[-1]


def open_storage(
    location: StorageLocation | str, *, clone_into: Path | None = None
) -> StorageProvider:
    """Open a workspace, returning the most capable provider its backing supports.

    ``clone_into`` is required for a ``github:`` location that is not on the machine yet;
    the clone is BLOCKING and belongs on a worker thread.
    """
    if isinstance(location, str):
        location = parse_location(location)

    if location.scheme == "github":
        if clone_into is None:
            raise StorageError("a GitHub workspace needs a directory to clone into")
        dest = clone_target(location, clone_into)
        if dest.exists() and (dest / ".git").exists():
            return GitHubStorage(dest)
        return GitHubStorage.clone(location.target, dest)

    path = location.path
    assert path is not None
    if location.scheme == "file":
        return LocalStorage(path)
    if location.scheme == "git":
        return _open_git(path)
    # Bare path: take whatever the directory can actually support.
    if find_repo_root(path) is None:
        return LocalStorage(path)
    return _open_git(path)


def _open_git(path: Path) -> GitStorage:
    """A git checkout, upgraded to :class:`GitHubStorage` when it has a remote."""
    storage = GitStorage(path)
    if storage.has_origin():
        return GitHubStorage(path, repo_root=storage.repo_root)
    return storage
