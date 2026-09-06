"""The ``.dplanner`` index: how a plan repository names the projects inside itself.

One line per project directory, relative to the file's own directory (an absolute path
also works), in the order a panel shows them. The CLI finds a project by walking up for
``project.dproj`` — or for this file, which is what lets a fresh clone (or an agent started
at the repository root) find the plan with zero configuration. A file with one line is the
pointer it always was; a plan repository that holds several projects lists them all, and
``dplanner library add <root>`` adds every one.

It lives here in ``core/storage`` because readers and writers sit on different layers:
``cli/discovery.py`` follows it, ``domain/seed.py`` appends to it the moment a project is
created inside a checkout, ``domain/relocate.py`` moves a line between two of them, and
none may import another's layer. The format itself is contract — see ``FORMAT.md``.

``WORKTREES_DIR`` lives beside it for the same reason: the worktrees Run Agent keeps under a
checkout are a sibling of this *file* — never inside a ``.dplanner/`` directory, which is
where an earlier layout failed for every project kept in a subfolder — and the plan
repository scan in ``domain/`` has to know to skip them.
"""

import os
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from dplanner.core.storage.git import find_repo_root

POINTER_FILE = ".dplanner"
WORKTREES_DIR = ".dplanner-worktrees"


def read_index(root: Path) -> list[str]:
    """The lines of the index at ``root``, stripped; [] when there is none."""
    index = root / POINTER_FILE
    if not index.is_file():
        return []
    return [line.strip() for line in index.read_text().splitlines() if line.strip()]


def resolve_index(root: Path) -> list[tuple[str, Path]]:
    """Each line with the directory it names, resolved against the index's own directory."""
    return [(line, (root / line).resolve()) for line in read_index(root)]


def write_index(root: Path, lines: Sequence[str]) -> None:
    (root / POINTER_FILE).write_text("".join(f"{line}\n" for line in lines))


def add_to_index(project_dir: Path) -> Path | None:
    """List ``project_dir`` in its repository's index, appended after what is there.

    None — and no write — when there is no enclosing repository, when the project *is* the
    repository root (the walk already finds it), or when a line already names it: a
    hand-written line is the user's word and is never rewritten, only kept company.
    """
    repo_root = find_repo_root(project_dir)
    if repo_root is None or repo_root.resolve() == project_dir.resolve():
        return None
    lines = read_index(repo_root)
    if any(target == project_dir.resolve() for _line, target in resolve_index(repo_root)):
        return None
    relative = PurePosixPath(*Path(os.path.relpath(project_dir, repo_root)).parts).as_posix()
    write_index(repo_root, [*lines, relative])
    return repo_root / POINTER_FILE


def remove_from_index(project_dir: Path) -> None:
    """Take ``project_dir`` out of its repository's index; the file goes when it empties.

    A line that leads nowhere is a refusal the CLI reports on every walk, so a project
    that moves or is deleted takes its line with it.
    """
    repo_root = find_repo_root(project_dir)
    if repo_root is None or not (repo_root / POINTER_FILE).is_file():
        return
    kept = [line for line, target in resolve_index(repo_root) if target != project_dir.resolve()]
    if kept:
        write_index(repo_root, kept)
    else:
        (repo_root / POINTER_FILE).unlink()
