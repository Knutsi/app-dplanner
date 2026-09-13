"""Where a git source points, what it costs to take in, and how to tell it has moved.

**The locator is three keys** — ``url``, ``ref``, ``path`` — validated on every read,
because a plan is shared and a colleague's ``spec.json`` is input. The validation is the
security boundary: an address that starts with a dash is an option, ``ext::`` is a shell
command dressed as a URL, and a ``path`` carrying a gitignore metacharacter would turn the
sparse-checkout pattern into a glob. Each of those is refused here, by character set, and
then the URL is passed after ``--`` as well.

**A credential is never part of it.** An address carrying ``user:password@`` is refused
with the sentence that says where the credentials come from instead — the person's own
git, on this computer. That is what keeps a secret out of a shared plan structurally,
rather than by anybody remembering.

**The checkout is a cache, never the plan.** A blobless, shallow, sparse clone under a
per-user directory the composition root names: megabytes of somebody else's repository,
reproducible from the remote, and pointless to commit. It is keyed on url + ref + path —
one directory per source — so two sources can never cross sparse patterns and import each
other's folder.

**The size guard runs before one blob is downloaded.** ``--filter=blob:none`` brings the
commit and its trees and no file contents, so the listing can count what a fetch would
take in and refuse — naming the folder and saying to pick one inside it — while nothing
has been downloaded. Counting *bytes* is not available: git cannot report a blob's size
without the blob, which is what ``GIT_NO_LAZY_FETCH`` is set to make loud rather than slow.

**A version is the file's git blob oid.** It is a content digest git has already computed
and hands back from a tree for free, and it is *per document* — which is why the commit id
must not be the version: a commit moves for every file in the repository, so a check would
report every document changed on any commit to any part of it.
"""

import hashlib
import logging
import re
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from time import time
from urllib.parse import urlsplit

from dplanner.core.storage.locations import canonical_remote, remote_label
from dplanner.domain.document_folder import FolderScan, is_document
from dplanner.domain.document_folder import snapshot as walk
from dplanner.domain.document_source import (
    Freshness,
    Locator,
    Snapshot,
    SourceUnavailableError,
)
from dplanner.modules.spec_git.client import (
    CHECKOUT_S,
    LOCAL_S,
    REMOTE_S,
    GitError,
    Ran,
    hardening,
    run_git,
)

logger = logging.getLogger(__name__)

KIND = "git"

# What one source takes in. Counted from the trees, before any content exists locally —
# git cannot answer "how many bytes" without downloading them, so the guard counts files.
MAX_FILES = 2_000
MAX_DOCUMENTS = 300

DEFAULT_REF = "HEAD"
CACHE_DAYS = 30  # A checkout nothing has fetched in this long is dropped on the next fetch.
HEAD_REF = "refs/dplanner/head"  # What we last took in; gc.auto is off, so it holds.

_SCHEMES = {"https": "https", "ssh": "ssh", "file": "file"}
_SCP = re.compile(r"^(?:[A-Za-z0-9._%+-]+@)?([A-Za-z0-9._-]+):(?!//)(.+)$")
_REF = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")
_PATH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_BLOB_MODES = ("100644", "100755")


@dataclass(frozen=True)
class Folder:
    """One directory of the remote, as the Add dialog lists them."""

    path: str  # "" is the whole repository.
    files: int
    documents: int

    @property
    def label(self) -> str:
        return self.path or "the whole repository"

    @property
    def refusal(self) -> str:
        """Why this folder is too much to take in, or "" — the dialog's and the fetch's
        one sentence, so a person meets the guard while choosing rather than afterwards."""
        return _too_big(self.label, self.files, self.documents)


@dataclass(frozen=True)
class Probe:
    """What one look at a remote found: where its head is, and what it holds."""

    commit: str
    ref: str  # The ref that was read — the resolved branch name when none was typed.
    folders: tuple[Folder, ...]


# -- the locator ---------------------------------------------------------------------------------


def parse_url(text: str) -> str:
    """An address as the host's Clone button gives it → the address we will use.

    ``ValueError`` carries the one sentence the dialog shows under the field.
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


NO_CREDENTIALS = (
    "take the user name and password out of the address — DPlanner uses the git "
    "credentials already on this computer"
)


def _checked_url(address: str, scheme: str) -> str:
    """An accepted address, or the sentence saying why not.

    A credential in the URL is the one refusal that is not about reachability: an address
    is written into the plan, and the plan is shared. ``git@host:path`` is the normal ssh
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


def scheme_of(url: str) -> str:
    """The one transport this address may use — the only one git is allowed."""
    scheme = urlsplit(url).scheme.lower()
    return _SCHEMES.get(scheme, "ssh")


def valid_locator(locator: Mapping[str, object]) -> Locator | None:
    """The locator as this kind understands it, or None — re-checked on every read."""
    url, ref, path = locator.get("url"), locator.get("ref"), locator.get("path", "")
    if not isinstance(url, str) or not isinstance(ref, str) or not isinstance(path, str):
        return None
    try:
        parse_url(url)
    except ValueError:
        return None
    if not _REF.match(ref) or ".." in ref or ref.endswith((".lock", "/")) or "@{" in ref:
        return None
    if path and (not _PATH.match(path) or ".." in PurePosixPath(path).parts):
        return None
    return {"url": url, "ref": ref, "path": path}


def open_url(locator: Locator) -> str:
    """Where a person opens it — an https browse address, when the host has one."""
    split = urlsplit(locator["url"])
    host = split.netloc.rpartition("@")[2].partition(":")[0]
    scp = _SCP.match(locator["url"])
    if scp is not None and "://" not in locator["url"]:
        host, repository = scp.group(1), scp.group(2)
    else:
        repository = split.path
    if not host or split.scheme == "file":
        return ""
    repository = repository.strip("/").removesuffix(".git")
    inside = f"/tree/{locator['ref']}/{locator['path']}".rstrip("/")
    return f"https://{host}/{repository}{inside}"


def summary(locator: Locator) -> str:
    """The source as one line — what a strip with no room for a URL says."""
    where = f" · {locator['path']}" if locator["path"] else ""
    return f"{remote_label(locator['url'])} @ {locator['ref']}{where}"


def cache_dir(cache_root: Path, locator: Locator) -> Path:
    """This source's checkout, under the per-user cache the composition root named.

    Keyed on all three: one directory per source, so two sources on one repository can
    never write each other's sparse pattern and import the wrong folder.
    """
    key = f"{canonical_remote(locator['url'])}\n{locator['ref']}\n{locator['path']}"
    return cache_root / hashlib.sha256(key.encode()).hexdigest()[:16]


# -- looking, fetching, checking -------------------------------------------------------------------


def probe(cache_root: Path, url: str, ref: str) -> Probe:
    """What the remote holds, without downloading a file: the Add dialog's listing."""
    address = parse_url(url)
    checked = valid_locator({"url": address, "ref": ref or DEFAULT_REF, "path": ""})
    if checked is None:
        raise SourceUnavailableError("that branch or tag name cannot be read")
    directory = cache_dir(cache_root, checked)
    with _refusing(checked):
        commit, _warnings = _bring_trees(directory, checked)
        rows = _tree(directory, checked, commit)
    return Probe(commit=commit, ref=checked["ref"], folders=_folders(rows))


def fetch(
    cache_root: Path,
    locator: Locator,
    known: Mapping[str, str],
    progress: Callable[[float], None] = lambda _f: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Snapshot:
    """The documents under the chosen folder, at the ref's current commit."""
    directory = cache_dir(cache_root, locator)
    _sweep(cache_root, directory)
    with _refusing(locator):
        commit, warnings = _bring_trees(directory, locator, cancelled)
        progress(0.15)
        rows = _tree(directory, locator, commit)
        too_big = _too_big(*_counts(rows, locator["path"]))
        if too_big:
            raise SourceUnavailableError(too_big)
        _materialise(directory, locator, commit, cancelled)
    progress(0.5)
    scan = FolderScan(root=directory, subdirectory=locator["path"])
    # The walk has the bytes locally, so it is handed no known versions: nothing is kept
    # back, and every document's version is replaced below by the oid git already knows.
    taken = walk(scan, {}, lambda fraction: progress(0.5 + fraction / 2), cancelled)
    oids = {key: oid for oid, key in rows}
    documents = tuple(
        replace(document, version=oids.get(document.key, document.version))
        for document in taken.documents
    )
    return replace(taken, documents=documents, notes=taken.notes + warnings)


def check(cache_root: Path, locator: Locator, known: Mapping[str, str]) -> Freshness:
    """What moved since ``known`` — one cheap question first, and trees only if it did."""
    if _SHA.match(locator["ref"]):
        return Freshness()  # A pinned commit never moves; nothing to ask anybody.
    directory = cache_dir(cache_root, locator)
    remote = _remote_head(cache_root, locator)
    if remote and remote == _local_head(directory):
        return Freshness()
    with _refusing(locator):
        commit, _warnings = _bring_trees(directory, locator)
        # Only what a fetch would take in: the walk's own rule, asked of a git tree, so a
        # picture beside a document can never be reported as a document that appeared.
        current = {key: oid for oid, key in _tree(directory, locator, commit) if is_document(key)}
    return Freshness(
        changed=tuple(key for key in current if key in known and current[key] != known[key]),
        added=tuple(key for key in current if key not in known),
        removed=tuple(key for key in known if key not in current),
    )


@contextmanager
def _refusing(locator: Locator) -> Iterator[None]:
    """Every git failure inside leaves as the one sentence a person reads."""
    try:
        yield
    except GitError as error:
        raise refusal(error, locator) from None


def refusal(error: GitError, locator: Locator) -> SourceUnavailableError:
    """One sentence for a person, and the rest to the log.

    Composed from what git said, never *by quoting* it: stderr can carry the address, and
    the address is the one thing a message here must never repeat.
    """
    logger.warning("git %s failed: %s", error.verb, error.stderr)
    label = remote_label(locator["url"]) or "the repository"
    said = error.stderr.lower()
    if error.timed_out:
        return SourceUnavailableError(f"{label} did not answer in time")
    for fragments, sentence, reconnect in _REFUSALS:
        if any(fragment in said for fragment in fragments):
            return SourceUnavailableError(
                sentence.format(label=label, ref=locator["ref"]), needs_reconnect=reconnect
            )
    return SourceUnavailableError(f"git {error.verb} against {label} failed")


# ``needs_reconnect`` means exactly one thing: a person at this computer can fix it. Not the
# network, not the ref — a refusal that sticks must be one a Connect button could clear.
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


# -- git, as this kind uses it ---------------------------------------------------------------------


def _git(
    directory: Path,
    locator: Locator,
    *args: str,
    timeout: float = LOCAL_S,
    cancelled: Callable[[], bool] = lambda: False,
    extra_env: dict[str, str] | None = None,
) -> Ran:
    hooks = directory.parent / "no-hooks"
    return run_git(
        ["-C", str(directory), *hardening(scheme_of(locator["url"]), hooks), *args],
        timeout=timeout,
        cancelled=cancelled,
        extra_env=extra_env,
    )


def _bring_trees(
    directory: Path,
    locator: Locator,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[str, tuple[str, ...]]:
    """The ref's commit here, with every tree and no file content: (commit, what to say).

    A directory that is not this source's repository — a half-written clone a killed run
    left, or a stale one from an older locator — is dropped and made again; that removes a
    whole class of "why is it importing somebody else's files".
    """
    if directory.is_dir() and not _is_ours(directory, locator):
        shutil.rmtree(directory, ignore_errors=True)
    said = ""
    if not directory.is_dir():
        said = _clone(directory, locator, cancelled)
    fetched = _git(
        directory,
        locator,
        "fetch",
        "--quiet",
        "--depth=1",
        "--no-tags",
        "--prune",
        "--filter=blob:none",
        "--",
        "origin",
        locator["ref"],
        timeout=REMOTE_S,
        cancelled=cancelled,
    )
    commit = _git(
        directory, locator, "rev-parse", "--verify", "--quiet", "FETCH_HEAD^{commit}"
    ).out.strip()
    _git(directory, locator, "update-ref", HEAD_REF, commit)
    return commit, _unfiltered(said + fetched.err)


def _unfiltered(said: str) -> tuple[str, ...]:
    """A server that does not support partial fetches warns, then sends every blob of the
    commit anyway — so the size guard measured a folder that was downloaded whole.
    ``--depth=1`` is the only bound git gives us there, and the person should be told."""
    if "filtering not recognized by server" not in said.lower():
        return ()
    return ("this server does not support partial fetches, so the whole commit was downloaded",)


def _clone(directory: Path, locator: Locator, cancelled: Callable[[], bool]) -> str:
    """A blobless, shallow clone with nothing checked out, landed by an atomic rename.

    The rename is the whole recovery story for a run that died halfway: a ``.partial`` is
    never trusted, and the next run deletes it unseen.
    """
    partial = directory.parent / f"{directory.name}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    directory.parent.mkdir(parents=True, exist_ok=True)
    args = [
        *hardening(scheme_of(locator["url"]), directory.parent / "no-hooks"),
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
    if not _SHA.match(locator["ref"]) and locator["ref"] != DEFAULT_REF:
        args += ["--branch", locator["ref"]]
    args += ["--", locator["url"], str(partial)]
    said = run_git(args, timeout=REMOTE_S, cancelled=cancelled).err
    partial.rename(directory)
    return said


def _is_ours(directory: Path, locator: Locator) -> bool:
    try:
        found = _git(directory, locator, "remote", "get-url", "origin").out.strip()
    except GitError:
        return False
    return canonical_remote(found) == canonical_remote(locator["url"])


def _tree(directory: Path, locator: Locator, commit: str) -> list[tuple[str, str]]:
    """(blob oid, key) for every file under the chosen folder, from the trees alone.

    ``GIT_NO_LAZY_FETCH`` is the environment variable and not ``--no-lazy-fetch``: the
    option is git 2.45 and later, where an unknown variable is ignored by every version.
    Its job is to make an accidental content read *fail* rather than quietly download the
    repository behind the guard's back.
    """
    args = ["ls-tree", "-r", "-z", commit]
    if locator["path"]:
        args += ["--", locator["path"]]
    listing = _git(directory, locator, *args, extra_env={"GIT_NO_LAZY_FETCH": "1"}).out
    rows: list[tuple[str, str]] = []
    prefix = f"{locator['path']}/" if locator["path"] else ""
    for record in listing.split("\0"):
        if not record:
            continue
        meta, _tab, path = record.partition("\t")
        mode, _space, rest = meta.partition(" ")
        if mode not in _BLOB_MODES:  # A symlink or a submodule is not a document.
            continue
        oid = rest.partition(" ")[2]
        rows.append((oid, path.removeprefix(prefix)))
    return rows


def _materialise(
    directory: Path, locator: Locator, commit: str, cancelled: Callable[[], bool]
) -> None:
    """Check out exactly the chosen folder, which is the one batch of blobs downloaded.

    The pattern is written to ``$GIT_DIR/info/sparse-checkout`` directly and **not** in
    cone mode: cone also materialises every file at the levels above the chosen folder,
    so a repository with a large asset at its root would come down despite the guard
    having measured the folder.
    """
    info = directory / ".git" / "info"
    if locator["path"]:
        info.mkdir(parents=True, exist_ok=True)
        (info / "sparse-checkout").write_text(f"/{locator['path']}/\n")
        _git(directory, locator, "config", "core.sparseCheckout", "true")
    _git(
        directory,
        locator,
        "checkout",
        "--quiet",
        "--detach",
        "--force",
        commit,
        timeout=CHECKOUT_S,
        cancelled=cancelled,
    )


def _remote_head(cache_root: Path, locator: Locator) -> str:
    """Where the ref stands on the remote — one round trip, no objects.

    A failure here is not a refusal: it only means the cheap answer is unavailable, and
    the caller falls through to the tree fetch, which words its own.
    """
    try:
        answer = run_git(
            [
                *hardening(scheme_of(locator["url"]), cache_root / "no-hooks"),
                "ls-remote",
                "--quiet",
                "--exit-code",
                "--",
                locator["url"],
                locator["ref"],
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


def _local_head(directory: Path) -> str:
    try:
        ran = run_git(["-C", str(directory), "rev-parse", "--verify", "--quiet", HEAD_REF])
    except GitError:
        return ""
    return ran.out.strip()


def _counts(rows: list[tuple[str, str]], path: str) -> tuple[str, int, int]:
    label = path or "the whole repository"
    return label, len(rows), sum(1 for _oid, key in rows if is_document(key))


def _folders(rows: list[tuple[str, str]]) -> tuple[Folder, ...]:
    """Every directory of the repository with what it holds, the root first."""
    files: dict[str, int] = {"": 0}
    documents: dict[str, int] = {"": 0}
    for _oid, key in rows:
        parts = PurePosixPath(key).parts[:-1]
        for depth in range(len(parts) + 1):
            where = "/".join(parts[:depth])
            files[where] = files.get(where, 0) + 1
            documents[where] = documents.get(where, 0) + (1 if is_document(key) else 0)
    ordered = sorted(files, key=lambda where: (where != "", where.casefold()))
    return tuple(
        Folder(path=where, files=files[where], documents=documents[where]) for where in ordered
    )


def _too_big(label: str, files: int, documents: int) -> str:
    if files > MAX_FILES:
        return (
            f"{label} holds {files:,} files — more than the {MAX_FILES:,} one source takes "
            "in. Pick a folder inside it."
        )
    if documents > MAX_DOCUMENTS:
        return (
            f"{label} holds {documents:,} documents — more than the {MAX_DOCUMENTS:,} one "
            "source takes in. Pick a folder inside it."
        )
    return ""


def _sweep(cache_root: Path, keep: Path) -> None:
    """Drop checkouts nothing has fetched in a long while.

    It runs inside a fetch, so it is always on a worker thread — a prune at construction
    would be an ``rmtree`` on the GUI thread — and it can only ever cost a re-clone, which
    is what makes a cache a cache.
    """
    cutoff = time() - CACHE_DAYS * 24 * 60 * 60
    for found in _cached(cache_root):
        if found != keep and found.stat().st_mtime < cutoff:
            shutil.rmtree(found, ignore_errors=True)


def _cached(cache_root: Path) -> list[Path]:
    try:
        return [found for found in cache_root.iterdir() if found.is_dir()]
    except OSError:
        return []
