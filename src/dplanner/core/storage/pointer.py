"""The ``.dplanner`` pointer file: how a repository names a workspace inside itself.

The CLI finds a product by walking up for ``product.json`` — or for this one-line file,
whose content is the workspace's path relative to the pointer's own directory. It lives
here in ``core/storage`` because both readers and writers need it and they sit on
different layers: ``cli/workspace.py`` follows it, ``domain/seed.py`` writes it the
moment a workspace is created inside a checkout, and neither may import the other's
layer. The format itself is contract — see ``FORMAT.md``.
"""

import os
from pathlib import Path

from dplanner.core.storage.git import find_repo_root

POINTER_FILE = ".dplanner"


def write_pointer(workspace: Path) -> Path | None:
    """Drop ``repo_root/.dplanner`` naming a workspace created inside a git checkout.

    None — and no write — when there is no enclosing repository, when the workspace *is*
    the repository root (the walk already finds it), or when a pointer already exists:
    a hand-written pointer is the user's word and is never clobbered.
    """
    repo_root = find_repo_root(workspace)
    if repo_root is None or repo_root == workspace:
        return None
    pointer = repo_root / POINTER_FILE
    if pointer.exists():
        return None
    pointer.write_text(os.path.relpath(workspace, repo_root) + "\n")
    return pointer
