"""A git repository as a document source: the locator, the fetch and the check.

The clone itself — the blobless, shallow, sparse checkout under a per-user cache, the size
guard, the listing, the subprocess door — is ``core/storage/sparse.py``'s, and this module
reads it. What is the spec kind's own is the shape of the locator (``url``, ``ref``,
``path`` in the spec index, re-validated on every read because a colleague's ``spec.json``
is input), which files count as documents (``domain/document_folder``'s one rule), how a
listing becomes a :class:`Snapshot` and a comparison a :class:`Freshness`, and the
translation of a git failure into the one sentence a person reads.

**A version is the file's git blob oid.** The walk over the checkout digests bodies, and
every version it computed is replaced by the oid the tree already carries — that is what
lets ``check`` name changed, added and gone documents from the trees alone, and why the
commit id must not be the version: it moves for every file in the repository.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from dplanner.core.storage.sparse import (
    DEFAULT_REF,
    Folder,
    GitError,
    Probe,
    SparseClone,
    folders,
    parse_url,
    sparse_dir,
    split_url,
    valid_path,
    valid_ref,
)
from dplanner.core.storage.sparse import refusal as explain
from dplanner.domain.document_folder import FolderScan, is_document
from dplanner.domain.document_folder import snapshot as walk
from dplanner.domain.document_source import (
    Freshness,
    Locator,
    Snapshot,
    SourceUnavailableError,
)

__all__ = [
    "DEFAULT_REF",
    "KIND",
    "Folder",
    "Probe",
    "browse_url",
    "cache_dir",
    "check",
    "fetch",
    "parse_url",
    "probe",
    "valid_locator",
]

KIND = "git"
# The per-user cache the clones land under, beside the library file: config_dir()/spec-git.
SPEC_GIT_CACHE = "spec-git"


# -- the locator ---------------------------------------------------------------------------------


def valid_locator(locator: Mapping[str, object]) -> Locator | None:
    """The locator as this kind understands it, or None — re-checked on every read."""
    url, ref, path = locator.get("url"), locator.get("ref"), locator.get("path", "")
    if not isinstance(url, str) or not isinstance(ref, str) or not isinstance(path, str):
        return None
    try:
        parse_url(url)
    except ValueError:
        return None
    if not valid_ref(ref) or not valid_path(path):
        return None
    return {"url": url, "ref": ref, "path": path}


def browse_url(locator: Locator) -> str:
    """Where a person opens it — an https browse address, when the host has one."""
    host, repository = split_url(locator["url"])
    if not host:
        return ""
    repository = repository.strip("/").removesuffix(".git")
    inside = f"/tree/{locator['ref']}/{locator['path']}".rstrip("/")
    return f"https://{host}/{repository}{inside}"


def cache_dir(cache_root: Path, locator: Locator) -> Path:
    """This source's checkout, under the per-user cache the composition root named."""
    return sparse_dir(cache_root, locator["url"], locator["ref"], locator["path"])


def _clone_of(cache_root: Path, locator: Locator) -> SparseClone:
    return SparseClone(cache_root, locator["url"], locator["ref"], locator["path"])


# -- looking, fetching, checking -------------------------------------------------------------------


def probe(cache_root: Path, url: str, ref: str) -> Probe:
    """What the remote holds, without downloading a file: the Add dialog's listing."""
    address = parse_url(url)
    ref = ref or DEFAULT_REF
    if not valid_ref(ref):
        raise SourceUnavailableError("that branch or tag name cannot be read")
    clone = SparseClone(cache_root, address, ref)
    with _refusing(clone):
        commit, _warnings = clone.bring_trees()
        rows = clone.tree(commit)
    return Probe(ref=ref, folders=folders(rows, is_document))


def fetch(
    cache_root: Path,
    locator: Locator,
    known: Mapping[str, str],
    progress: Callable[[float], None] = lambda _f: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Snapshot:
    """The documents under the chosen folder, at the ref's current commit."""
    clone = _clone_of(cache_root, locator)
    clone.sweep()
    with _refusing(clone):
        commit, warnings = clone.bring_trees(cancelled)
        progress(0.15)
        rows = clone.tree(commit)
        held = Folder(clone.path, len(rows), sum(1 for _oid, key in rows if is_document(key)))
        if held.refusal:
            raise SourceUnavailableError(held.refusal)
        clone.materialise(commit, cancelled)
    progress(0.5)
    scan = FolderScan(root=clone.directory, subdirectory=clone.path)
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
    clone = _clone_of(cache_root, locator)
    if clone.pinned:
        return Freshness()  # A pinned commit never moves; nothing to ask anybody.
    remote = clone.remote_head()
    if remote and remote == clone.local_head():
        return Freshness()
    with _refusing(clone):
        commit, _warnings = clone.bring_trees()
        # Only what a fetch would take in: the walk's own rule, asked of a git tree, so a
        # picture beside a document can never be reported as a document that appeared.
        current = {key: oid for oid, key in clone.tree(commit) if is_document(key)}
    return Freshness(
        changed=tuple(key for key in current if key in known and current[key] != known[key]),
        added=tuple(key for key in current if key not in known),
        removed=tuple(key for key in known if key not in current),
    )


@contextmanager
def _refusing(clone: SparseClone) -> Iterator[None]:
    """Every git failure inside leaves as the one sentence a person reads. ``fixable_here``
    becomes ``needs_reconnect``: a refusal that sticks must be one Connect could clear."""
    try:
        yield
    except GitError as error:
        said = explain(error, clone.url, clone.ref)
        raise SourceUnavailableError(said.sentence, needs_reconnect=said.fixable_here) from None
