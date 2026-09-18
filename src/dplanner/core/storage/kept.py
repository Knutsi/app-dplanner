"""A clone the application keeps for a person who never chose a folder.

The second clone door, beside :mod:`sparse`. That one fetches a folder of somebody else's
repository to *read* — blobless, shallow, sparse, a cache that can be wiped. This one makes
a **working checkout**: a plain, full ``git clone`` a person or an agent can commit and
push in, kept under the per-user configuration directory so a verb that needs the
repository on this machine (Run Agent, publishing a report) has one without anybody
picking a destination. It lands in ``<root>/checkouts/<name>-<digest>``, one directory per
repository whatever ref or position a project names, and **never inside a plan repository,
a project directory or the person's repositories folder** — those are theirs, and a clone
nobody asked for must not appear among them.

The clone is hardened only *while it is made*: the transport is the one the validated URL
named, hooks are pointed at nothing and no template directory is copied in, but through
the environment rather than ``-c`` — ``git clone`` writes command-line ``-c`` settings into
the new repository's config, and a working checkout must come out an ordinary repository,
hooks and symlinks and all, or an agent would find git behaving oddly there for reasons
nobody can see. A ``.partial`` directory is the recovery story for a run that dies halfway,
as it is for the cache: never trusted, renamed into place only when the clone is complete.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

from dplanner.core.storage.git import canonical_remote
from dplanner.core.storage.sparse import (
    CHECKOUT_S,
    hardening,
    parse_url,
    remove_tree,
    run_git,
    scheme_of,
)

CHECKOUTS_DIR = "checkouts"
# Left out of the clone-time hardening: the checkout must be an ordinary working tree.
_LEFT_TO_GIT = ("core.symlinks", "advice.detachedHead")


def kept_dir(root: Path, url: str) -> Path:
    """Where the kept clone of ``url`` stands under ``root`` (the configuration directory):
    the repository's own name for a person reading the directory, and a digest of its
    canonical remote so two spellings of one repository share a clone."""
    canonical = canonical_remote(url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    name = canonical.rsplit("/", 1)[-1] or "repository"
    return root / CHECKOUTS_DIR / f"{name}-{digest}"


def is_kept(path: Path, root: Path) -> bool:
    """Whether ``path`` is a clone this application keeps under ``root``."""
    try:
        return path.expanduser().resolve().is_relative_to((root / CHECKOUTS_DIR).resolve())
    except OSError:
        return False


def clone_full(url: str, dest: Path, cancelled: Callable[[], bool] = lambda: False) -> None:
    """BLOCKING — a full clone of ``url`` into ``dest``, landed by an atomic rename.

    ``ValueError`` for an address the door refuses; :class:`sparse.GitError` when git does.
    """
    address = parse_url(url)
    partial = dest.parent / f"{dest.name}.partial"
    remove_tree(partial)
    dest.parent.mkdir(parents=True, exist_ok=True)
    settings = [*hardening(scheme_of(address), dest.parent / "no-hooks"), "-c", "init.templateDir="]
    pairs = [
        pair for pair in settings[1::2] if not pair.startswith(tuple(f"{k}=" for k in _LEFT_TO_GIT))
    ]
    env = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for index, pair in enumerate(pairs):
        key, _, value = pair.partition("=")
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    run_git(
        ["clone", "--quiet", "--origin", "origin", "--", address, str(partial)],
        timeout=CHECKOUT_S,
        cancelled=cancelled,
        extra_env=env,
    )
    partial.rename(dest)
