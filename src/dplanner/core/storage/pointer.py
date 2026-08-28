"""The ``.dplanner`` pointer file: how a repository names the project inside itself.

The CLI finds a project by walking up for ``project.dproj`` — or for this one-line file,
whose content is the project directory's path relative to the pointer's own directory. It
is what lets a fresh clone (or an agent started at the repository root) find the plan with
zero configuration. It lives here in ``core/storage`` because both readers and writers
need it and they sit on different layers: ``cli/discovery.py`` follows it,
``domain/seed.py`` writes it the moment a project is created inside a checkout, and
neither may import the other's layer. The format itself is contract — see ``FORMAT.md``.
"""

import os
from pathlib import Path

from dplanner.core.storage.git import find_repo_root

POINTER_FILE = ".dplanner"


def write_pointer(project_dir: Path) -> Path | None:
    """Drop ``repo_root/.dplanner`` naming a project created inside a git checkout.

    None — and no write — when there is no enclosing repository, when the project *is*
    the repository root (the walk already finds it), or when a pointer already exists:
    a hand-written pointer is the user's word and is never clobbered.
    """
    repo_root = find_repo_root(project_dir)
    if repo_root is None or repo_root == project_dir:
        return None
    pointer = repo_root / POINTER_FILE
    if pointer.exists():
        return None
    pointer.write_text(os.path.relpath(project_dir, repo_root) + "\n")
    return pointer
