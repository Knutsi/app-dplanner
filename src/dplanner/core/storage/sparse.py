"""A repository and a folder in it, fetched on demand into a cache and read-only.

This is the clone door any feature that *reads* somebody else's repository goes through: a
blobless, shallow, sparse clone under a per-user cache root the caller names, keyed on the
remote, the ref and the folder — one directory per position, so two positions in one
repository can never cross sparse patterns and read each other's folder. It never commits
and never pushes; a cache that is wiped costs one tree fetch to rebuild, which is what makes
it a cache. It knows nothing about documents: a caller that counts them hands in the
predicate that says what one is.

**The address is validated on every read**, because the plan it came from is shared and a
colleague's file is input. The validation is the security boundary: an address that starts
with a dash is an option, ``ext::`` is a shell command dressed as a URL, and a ``path``
carrying a gitignore metacharacter would turn the sparse-checkout pattern into a glob. Each
of those is refused here, by character set, and then the URL is passed after ``--`` as well.
**A credential is never part of it**: an address carrying ``user:password@`` is refused
with the sentence that says where the credentials come from instead — the person's own git,
on this computer — which keeps a secret out of a shared plan structurally.

**The size guard runs before one blob is downloaded.** ``--filter=blob:none`` brings the
commit and its trees and no file contents, so the listing can count what a checkout would
take in and refuse — naming the folder and saying to pick one inside it — while nothing has
been downloaded. Counting *bytes* is not available: git cannot report a blob's size without
the blob, which is what ``GIT_NO_LAZY_FETCH`` is set to make loud rather than slow.

**A file's version is its git blob oid.** It is a content digest git has already computed
and hands back from a tree for free, and it is *per file* — which is why the commit id must
not be the version: a commit moves for every file in the repository, so a check would
report every document changed on any commit to any part of it.

**A worker thread must never hang.** A fetch runs off the GUI thread, and git will happily
sit forever at a credential prompt, an unknown host key or a dead server. Four locks:
``GIT_TERMINAL_PROMPT=0``, ``GIT_ASKPASS`` set-but-empty (which short-circuits both
``core.askPass`` and ``SSH_ASKPASS`` inside git), ``SSH_ASKPASS_REQUIRE=never`` beside an
``ssh -o BatchMode=yes``, and ``stdin`` closed. Then a timeout on every call and a poll loop
that kills the whole **process group** — killing only ``git`` leaves ``ssh`` holding the
pipes. **The environment is otherwise the person's**, which is what makes "your own git
credentials do the auth" true: their credential helper, their agent, their ``insteadOf``
rewrites and their proxy all work untouched. Only what would aim us at the wrong repository
is stripped.

``core/storage/git.py`` is the storage provider's door and is bound to one checkout; this
one is bound to none, which is why it is a second door rather than a method on that one.
"""

import hashlib
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import monotonic, time
from urllib.parse import urlsplit

from dplanner.core.storage.git import canonical_remote, remote_label

logger = logging.getLogger(__name__)

# What one clone takes in. Counted from the trees, before any content exists locally — git
# cannot answer "how many bytes" without downloading them, so the guard counts files.
MAX_FILES = 2_000
MAX_DOCUMENTS = 300

DEFAULT_REF = "HEAD"  # The remote's default branch, whatever it is called.
CACHE_DAYS = 30  # A clone nothing has fetched in this long is dropped on the next fetch.
HEAD_REF = "refs/dplanner/head"  # What we last took in; gc.auto is off, so it holds.

# A local command answers at once; a network one may not; a checkout carries the batched
# blob fetch behind it.
LOCAL_S = 20.0
REMOTE_S = 120.0
CHECKOUT_S = 300.0
POLL_S = 0.2

NO_CREDENTIALS = (
    "take the user name and password out of the address — DPlanner uses the git "
    "credentials already on this computer"
)

_SCHEMES = {"https": "https", "ssh": "ssh", "file": "file"}
_SCP = re.compile(r"^(?:[A-Za-z0-9._%+-]+@)?([A-Za-z0-9._-]+):(?!//)(.+)$")
_REF = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")
_PATH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_BLOB_MODES = ("100644", "100755")

# -- the address ----------------------------------------------------------------------------------


def parse_url(text: str) -> str:
    """An address as the host's Clone button gives it → the address we will use.

    ``ValueError`` carries the one sentence a dialog shows under the field.
    """
    address = text.strip()
    if not address:
        raise ValueError("paste the address of a git repository")
    if address.startswith("-"):
        raise ValueError("a repository address cannot start with a dash")
    if any(character.isspace() or ord(character) < 32 for character in address):
        raise ValueError("a repository address has no spaces")
    scheme = urlsplit(address).scheme.lower()
    if scheme == "http":
        raise ValueError("use the https address — a plain http remote is not encrypted")
    if scheme == "git":
        raise ValueError("git:// is unauthenticated — use the https or ssh address")
    if scheme in _SCHEMES:
        return _checked_url(address, scheme)
    if scheme:
        raise ValueError("DPlanner reads https, ssh and file:// repositories")
    if _SCP.match(address):
        return _checked_url(address, "ssh")
    if address.startswith(("/", "~", ".")) or re.match(r"^[A-Za-z]:[\\/]", address):
        raise ValueError("a folder on this computer is a Folder source, not a Git repository")
    raise ValueError("that address names no repository — paste the URL the Clone button gives")


def _checked_url(address: str, scheme: str) -> str:
    """An accepted address, or the sentence saying why not.

    A credential in the URL is the one refusal that is not about reachability: an address
    is written into a plan, and the plan is shared. ``git@host:path`` is the normal ssh
    spelling and is fine; a *password* in the userinfo never is.
    """
    userinfo = _authority(address, scheme).rpartition("@")[0]
    if userinfo and (scheme == "https" or ":" in userinfo):
        raise ValueError(NO_CREDENTIALS)
    if not _path_of(address, scheme):
        raise ValueError("that address names no repository — paste the URL the Clone button gives")
    return address


def _authority(address: str, scheme: str) -> str:
    scp = _SCP.match(address)
    if scheme == "ssh" and scp is not None and "://" not in address:
        return address.partition(":")[0]
    return urlsplit(address).netloc


def _path_of(address: str, scheme: str) -> str:
    scp = _SCP.match(address)
    if scheme == "ssh" and scp is not None and "://" not in address:
        return scp.group(2).strip("/")
    return urlsplit(address).path.strip("/")


def split_url(url: str) -> tuple[str, str]:
    """(host, repository path) of an accepted address — "" for a host when it has none."""
    split = urlsplit(url)
    scp = _SCP.match(url)
    if scp is not None and "://" not in url:
        return scp.group(1), scp.group(2)
    host = split.netloc.rpartition("@")[2].partition(":")[0]
    return "" if split.scheme == "file" else host, split.path


def scheme_of(url: str) -> str:
    """The one transport this address may use — the only one git is allowed."""
    scheme = urlsplit(url).scheme.lower()
    return _SCHEMES.get(scheme, "ssh")


def valid_ref(ref: str) -> bool:
    """A branch, a tag or a commit id that is safe to hand git after ``--``."""
    return (
        bool(_REF.match(ref))
        and ".." not in ref
        and not ref.endswith((".lock", "/"))
        and "@{" not in ref
    )


def valid_path(path: str) -> bool:
    """A folder that is safe as a sparse-checkout pattern: no glob character, no ``..``."""
    return not path or (bool(_PATH.match(path)) and ".." not in PurePosixPath(path).parts)


def sparse_dir(cache_root: Path, url: str, ref: str, path: str) -> Path:
    """Where one position's clone lives under the cache root.

    Keyed on all three: one directory per position, so two positions on one repository can
    never write each other's sparse pattern and read the wrong folder. The digest is part of
    the on-disk contract — a change to it would leave every existing cache behind.
    """
    key = f"{canonical_remote(url)}\n{ref}\n{path}"
    return cache_root / hashlib.sha256(key.encode()).hexdigest()[:16]


# -- what a listing holds ------------------------------------------------------------------------


@dataclass(frozen=True)
class Folder:
    """One directory of the remote, with what it holds: every file, and the ones the
    caller's predicate picked out as documents."""

    path: str  # "" is the whole repository.
    files: int
    documents: int

    @property
    def label(self) -> str:
        return self.path or "the whole repository"

    @property
    def refusal(self) -> str:
        """Why this folder is too much to take in, or "" — the one sentence a dialog and a
        fetch both use, so a person meets the guard while choosing rather than afterwards."""
        return too_big(self.label, self.files, self.documents)


@dataclass(frozen=True)
class Probe:
    """What one look at a remote found."""

    ref: str  # The ref that was read.
    folders: tuple[Folder, ...]


def too_big(label: str, files: int, documents: int) -> str:
    """Why this folder is more than one clone takes in, or "".

    Short on purpose: it stands in a dialog's footer status slot beside two buttons, and a
    reason that does not fit widens the dialog. What the person can act on is which folder
    and how much is in it — the cap itself is the application's and teaches nothing.
    """
    if files > MAX_FILES:
        return f"{label} holds {files:,} files — pick a folder inside it"
    if documents > MAX_DOCUMENTS:
        return f"{label} holds {documents:,} documents — pick a folder inside it"
    return ""


def folders(
    rows: Sequence[tuple[str, str]], is_document: Callable[[str], bool]
) -> tuple[Folder, ...]:
    """Every directory of a listing with what it holds, the root first."""
    files: dict[str, int] = {"": 0}
    documents: dict[str, int] = {"": 0}
    for _oid, key in rows:
        parts = PurePosixPath(key).parts[:-1]
        counted = 1 if is_document(key) else 0
        for depth in range(len(parts) + 1):
            where = "/".join(parts[:depth])
            files[where] = files.get(where, 0) + 1
            documents[where] = documents.get(where, 0) + counted
    ordered = sorted(files, key=lambda where: (where != "", where.casefold()))
    return tuple(
        Folder(path=where, files=files[where], documents=documents[where]) for where in ordered
    )


# -- the clone ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SparseClone:
    """One position — a repository, a ref, a folder — and the clone that stands for it.

    Constructing one validates all three, so nothing reaches git through an address that
    was not checked; ``ValueError`` carries the sentence.
    """

    cache_root: Path
    url: str
    ref: str = DEFAULT_REF
    path: str = ""

    def __post_init__(self) -> None:
        parse_url(self.url)
        if not valid_ref(self.ref):
            raise ValueError("that branch or tag name cannot be read")
        if not valid_path(self.path):
            raise ValueError("that folder name cannot be read")

    @property
    def directory(self) -> Path:
        return sparse_dir(self.cache_root, self.url, self.ref, self.path)

    @property
    def pinned(self) -> bool:
        """Whether the ref is a commit id — which never moves, so nobody need be asked."""
        return bool(_SHA.match(self.ref))

    def bring_trees(
        self, cancelled: Callable[[], bool] = lambda: False
    ) -> tuple[str, tuple[str, ...]]:
        """The ref's commit here, with every tree and no file content: (commit, what to say).

        A directory that is not this position's repository — a half-written clone a killed
        run left, or a stale one from an older address — is dropped and made again; that
        removes a whole class of "why is it reading somebody else's files".
        """
        directory = self.directory
        if directory.is_dir() and not self._is_ours():
            remove_tree(directory)
        said = ""
        if not directory.is_dir():
            said = self._clone(cancelled)
        fetched = self._git(
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            "--prune",
            "--filter=blob:none",
            "--",
            "origin",
            self.ref,
            timeout=REMOTE_S,
            cancelled=cancelled,
        )
        commit = self._git("rev-parse", "--verify", "--quiet", "FETCH_HEAD^{commit}").out.strip()
        self._git("update-ref", HEAD_REF, commit)
        return commit, _unfiltered(said + fetched.err)

    def tree(self, commit: str) -> list[tuple[str, str]]:
        """(blob oid, key) for every file under the folder, from the trees alone.

        ``GIT_NO_LAZY_FETCH`` is the environment variable and not ``--no-lazy-fetch``: the
        option is git 2.45 and later, where an unknown variable is ignored by every version.
        Its job is to make an accidental content read *fail* rather than quietly download
        the repository behind the guard's back.
        """
        args = ["ls-tree", "-r", "-z", commit]
        if self.path:
            args += ["--", self.path]
        listing = self._git(*args, extra_env={"GIT_NO_LAZY_FETCH": "1"}).out
        rows: list[tuple[str, str]] = []
        prefix = f"{self.path}/" if self.path else ""
        for record in listing.split("\0"):
            if not record:
                continue
            meta, _tab, path = record.partition("\t")
            mode, _space, rest = meta.partition(" ")
            if mode not in _BLOB_MODES:  # A symlink or a submodule is not a file to read.
                continue
            oid = rest.partition(" ")[2]
            rows.append((oid, path.removeprefix(prefix)))
        return rows

    def materialise(self, commit: str, cancelled: Callable[[], bool] = lambda: False) -> None:
        """Check out exactly the folder, which is the one batch of blobs downloaded.

        The pattern is written to ``$GIT_DIR/info/sparse-checkout`` directly and **not** in
        cone mode: cone also materialises every file at the levels above the chosen folder,
        so a repository with a large asset at its root would come down despite the guard
        having measured the folder.
        """
        directory = self.directory
        if self.path:
            info = directory / ".git" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "sparse-checkout").write_text(
                f"/{self.path}/\n", encoding="utf-8", newline="\n"
            )
            self._git("config", "core.sparseCheckout", "true")
        self._git(
            "checkout",
            "--quiet",
            "--detach",
            "--force",
            commit,
            timeout=CHECKOUT_S,
            cancelled=cancelled,
        )

    def remote_head(self) -> str:
        """Where the ref stands on the remote — one round trip, no objects.

        A failure here is not a refusal: it only means the cheap answer is unavailable, and
        the caller falls through to the tree fetch, which words its own.
        """
        try:
            answer = run_git(
                [
                    *hardening(scheme_of(self.url), self.cache_root / "no-hooks"),
                    "ls-remote",
                    "--quiet",
                    "--exit-code",
                    "--",
                    self.url,
                    self.ref,
                    f"{self.ref}^{{}}",  # A pattern matches a ref's tail, so ask for both.
                ],
                timeout=REMOTE_S,
            ).out
        except GitError:
            return ""
        peeled = {}
        for line in answer.splitlines():
            oid, _tab, name = line.partition("\t")
            peeled[name.strip()] = oid.strip()
        for name, oid in peeled.items():
            if name.endswith("^{}"):  # An annotated tag: the commit it points at.
                return oid
        return next(iter(peeled.values()), "")

    def local_head(self) -> str:
        """The commit last taken in, or "" while nothing has been."""
        try:
            ran = run_git(["-C", str(self.directory), "rev-parse", "--verify", "--quiet", HEAD_REF])
        except GitError:
            return ""
        return ran.out.strip()

    def sweep(self) -> None:
        """Drop the other clones under the cache root that nothing has fetched in a long while.

        It runs inside a fetch, so it is always on a worker thread — a prune at construction
        would be an ``rmtree`` on the GUI thread — and it can only ever cost a re-clone,
        which is what makes a cache a cache.
        """
        cutoff = time() - CACHE_DAYS * 24 * 60 * 60
        keep = self.directory
        for found in _cached(self.cache_root):
            if found != keep and found.stat().st_mtime < cutoff:
                remove_tree(found)

    # -- internals ---------------------------------------------------------------------------------

    def _git(
        self,
        *args: str,
        timeout: float = LOCAL_S,
        cancelled: Callable[[], bool] = lambda: False,
        extra_env: dict[str, str] | None = None,
    ) -> "Ran":
        hooks = self.cache_root / "no-hooks"
        return run_git(
            ["-C", str(self.directory), *hardening(scheme_of(self.url), hooks), *args],
            timeout=timeout,
            cancelled=cancelled,
            extra_env=extra_env,
        )

    def _clone(self, cancelled: Callable[[], bool]) -> str:
        """A blobless, shallow clone with nothing checked out, landed by an atomic rename.

        The rename is the whole recovery story for a run that died halfway: a ``.partial``
        is never trusted, and the next run deletes it unseen.
        """
        directory = self.directory
        partial = directory.parent / f"{directory.name}.partial"
        remove_tree(partial)
        directory.parent.mkdir(parents=True, exist_ok=True)
        args = [
            *hardening(scheme_of(self.url), self.cache_root / "no-hooks"),
            # No template directory, so ``init.templateDir``'s hooks never land in the clone.
            "-c",
            "init.templateDir=",
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-tags",
            "--depth=1",
            "--filter=blob:none",
            "--origin",
            "origin",
        ]
        if not self.pinned and self.ref != DEFAULT_REF:
            args += ["--branch", self.ref]
        args += ["--", self.url, str(partial)]
        said = run_git(args, timeout=REMOTE_S, cancelled=cancelled).err
        partial.rename(directory)
        return said

    def _is_ours(self) -> bool:
        try:
            found = self._git("remote", "get-url", "origin").out.strip()
        except GitError:
            return False
        return canonical_remote(found) == canonical_remote(self.url)


def _unfiltered(said: str) -> tuple[str, ...]:
    """A server that does not support partial fetches warns, then sends every blob of the
    commit anyway — so the size guard measured a folder that was downloaded whole.
    ``--depth=1`` is the only bound git gives us there, and the person should be told."""
    if "filtering not recognized by server" not in said.lower():
        return ()
    return ("this server does not support partial fetches, so the whole commit was downloaded",)


def remove_tree(directory: Path) -> None:
    """Delete a cache directory, git objects included.

    git writes its pack and object files read-only, and on Windows that is enough to make
    ``shutil.rmtree`` fail on every one of them — silently, under ``ignore_errors``, leaving
    a half-deleted directory that is neither ours nor absent. The next fetch then ran
    against it and reported "not a git repository". The handler clears the bit and retries,
    which is the documented recipe; a directory that is already gone is fine.
    """

    def unlock_and_retry(function: Callable[[str], object], path: str, _exc: BaseException) -> None:
        with suppress(OSError):
            Path(path).chmod(stat.S_IWRITE)
            function(path)

    if directory.exists():
        shutil.rmtree(directory, onexc=unlock_and_retry)


def _cached(cache_root: Path) -> list[Path]:
    try:
        return [found for found in cache_root.iterdir() if found.is_dir()]
    except OSError:
        return []


# -- what went wrong, for a person --------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    """One sentence for a person. ``fixable_here`` means exactly one thing: somebody at this
    computer can clear it — a credential, a host key — not the network and not the ref."""

    sentence: str
    fixable_here: bool = False


def refusal(error: "GitError", url: str, ref: str) -> Refusal:
    """One sentence for a person, and the rest to the log.

    Composed from what git said, never *by quoting* it: stderr can carry the address, and
    the address is the one thing a message here must never repeat.
    """
    logger.warning("git %s failed: %s", error.verb, error.stderr)
    label = remote_label(url) or "the repository"
    said = error.stderr.lower()
    if error.timed_out:
        return Refusal(f"{label} did not answer in time")
    for fragments, sentence, fixable in _REFUSALS:
        if any(fragment in said for fragment in fragments):
            return Refusal(sentence.format(label=label, ref=ref), fixable)
    return Refusal(f"git {error.verb} against {label} failed")


_REFUSALS: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (
        (
            "authentication failed",
            "could not read username",
            "terminal prompts disabled",
            "permission denied",
            "invalid username or token",
            "403",
        ),
        "{label} refused the git credentials on this computer",
        True,
    ),
    (
        ("repository not found", "does not exist", "not found", "404"),
        "{label} is not there, or this computer's git account cannot see it",
        True,
    ),
    (
        ("host key verification failed",),
        "{label}'s SSH host key is not known here — connect once with git in a terminal",
        True,
    ),
    (
        ("could not resolve host", "connection refused", "connection timed out", "unreachable"),
        "cannot reach {label} — check the network",
        False,
    ),
    (
        ("couldn't find remote ref", "unknown revision", "not our ref", "no such ref"),
        "{label} has no branch or tag called {ref}",
        False,
    ),
    (
        ("unadvertised object",),
        "{label} will not serve a single commit — use a branch or tag name",
        False,
    ),
    (("not allowed", "transport"), "that address uses a transport DPlanner does not read", False),
)


# -- the subprocess door -------------------------------------------------------------------------

# Aimed at the wrong repository by a shell that carried them — Run Agent exports an
# environment into the shells it opens, and a developer's shell may hold GIT_DIR.
_STRIPPED = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CONFIG",
)

_FORCED = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_LFS_SKIP_SMUDGE": "1",  # No second tool runs inside our checkout.
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",  # One language, which is what lets ``refusal`` read what git said.
}

_BATCH_SSH = "ssh -o BatchMode=yes -o ConnectTimeout=10"

# Its own process group, so a kill reaches the ssh or the credential helper git started.
# sys.platform is compared inline at each use rather than kept in a constant: mypy narrows on
# the comparison and then checks each branch only against the platform that reaches it. A
# constant is opaque to it, and `mypy --platform win32` reported os.killpg, os.getpgid and
# signal.SIGKILL missing from a branch Windows never runs.
_NEW_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_git_path: str | None = None


@dataclass(frozen=True)
class Ran:
    """What one git command said. ``err`` matters on success too: a server that ignores
    ``--filter`` warns there and downloads everything anyway."""

    out: str
    err: str


class GitError(Exception):
    """A git command failed. ``stderr`` is for the log; the sentence a person reads is
    composed from it by :func:`refusal`, because stderr can carry a URL."""

    def __init__(self, verb: str, stderr: str, *, timed_out: bool = False) -> None:
        super().__init__(f"git {verb}: {stderr.strip() or 'failed'}")
        self.verb = verb
        self.stderr = stderr
        self.timed_out = timed_out


def git_path() -> str | None:
    """Where ``git`` is, or None. Only a positive answer is remembered: a person who
    installs git while the window is open must not be told "not installed" forever."""
    global _git_path
    if _git_path is None:
        _git_path = shutil.which("git")
    return _git_path


def hardening(scheme: str, hooks_path: Path) -> list[str]:
    """The ``-c`` settings every invocation carries, whatever the person's config says.

    One transport is allowed and it is the one the validated URL named — ``ext::`` is a
    shell command dressed as a URL and is allowed by default for a direct invocation.
    Symlinks are not created in the checkout, so a repository carrying ``evil -> ~/.ssh``
    lands as a text file; hooks are pointed at a path that cannot exist, so neither the
    repository's nor the person's global ``core.hooksPath`` can run anything here.
    """
    return [
        "-c",
        "protocol.allow=never",
        "-c",
        f"protocol.{scheme}.allow=always",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.quotePath=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.askPass=",
        "-c",
        f"core.hooksPath={hooks_path}",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "fetch.recurseSubmodules=false",
        "-c",
        "submodule.recurse=false",
        "-c",
        "advice.detachedHead=false",
    ]


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The person's environment with the four prompt locks on and the aiming vars off."""
    env = {key: value for key, value in os.environ.items() if key not in _STRIPPED}
    env.update(_FORCED)
    # Only when they have not chosen one themselves: BatchMode turns a passphrase prompt
    # or an unknown host key into a refusal we can word, instead of a worker that hangs.
    if not env.get("GIT_SSH_COMMAND") and not env.get("GIT_SSH"):
        env["GIT_SSH_COMMAND"] = _BATCH_SSH
    env.update(extra or {})
    return env


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = LOCAL_S,
    cancelled: Callable[[], bool] = lambda: False,
    extra_env: dict[str, str] | None = None,
) -> Ran:
    """Run git and return what it said, or raise :class:`GitError`.

    ``subprocess.run(timeout=…)`` is not usable here: a five-minute clone has to notice
    that the person pressed Cancel, so the wait is a poll loop instead.
    """
    git = git_path()
    if git is None:
        raise GitError(args[0] if args else "", "git is not installed")
    # Every argument was validated by the SparseClone that built it; stdin is closed so
    # nothing can be asked of a worker thread.
    started: subprocess.Popen[bytes] = subprocess.Popen(
        [git, *args],
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment(extra_env),
        start_new_session=sys.platform != "win32",
        creationflags=_NEW_GROUP if sys.platform == "win32" else 0,
    )
    deadline = monotonic() + timeout
    while True:
        try:
            out, err = started.communicate(timeout=POLL_S)
            break
        except subprocess.TimeoutExpired:
            expired = monotonic() > deadline
            if expired or cancelled():
                _end(started)
                raise GitError(_verb(args), "timed out", timed_out=expired) from None
    said = err.decode("utf-8", "replace")
    if started.returncode != 0:
        raise GitError(_verb(args), said)
    return Ran(out=out.decode("utf-8", "replace"), err=said)


def _verb(args: Sequence[str]) -> str:
    """What was being done, for a log line — never the arguments, which carry the URL.

    The first word that is neither an option nor the value of one: ``-c`` and ``-C`` each
    take the argument after them, and ``protocol.allow=never`` is not a verb.
    """
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ("-c", "-C"):
            skip = True
            continue
        if not arg.startswith("-"):
            return arg
    return ""


def _end(started: "subprocess.Popen[bytes]") -> None:
    with suppress(OSError):
        if sys.platform == "win32":
            started.kill()
        else:
            os.killpg(os.getpgid(started.pid), signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired, ValueError):
        started.communicate(timeout=LOCAL_S)
