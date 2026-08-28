"""What a brand-new library, and a brand-new project, contain.

A real library with nothing in it, not a sample. A planner that arrives pre-filled with
invented projects makes the first real one harder to see, and every fake row is something a
person has to delete before they can start. The empty index says so in words instead.
"""

import json
from pathlib import Path

from dplanner.core.formats import FORMAT_KEY
from dplanner.core.fsio import write_atomic
from dplanner.core.storage.pointer import write_pointer
from dplanner.domain.library_file import write_library_file
from dplanner.domain.migrations import FORMAT
from dplanner.domain.model import Project
from dplanner.domain.store import PROJECT_META


def create_library(path: Path) -> None:
    """Write an empty library file — the seed for a library that does not exist yet."""
    write_library_file(path, [])


def seed_project(directory: Path, title: str) -> Path:
    """Write a brand-new project: its ``project.dproj`` and the repo-root pointer.

    A project born inside a git checkout leaves a ``.dplanner`` pointer at the repository
    root, so the CLI's walk finds the plan from anywhere in the checkout — for everyone who
    clones it — without a line of configuration.

    The meta written here is deliberately the same shape ``LibraryStore._write_meta``
    produces for a project, and ``LibraryStore.create_project`` loads it straight back —
    which is the round trip that keeps the two from drifting.
    """
    directory = directory.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    project = Project(title=title, folder_name=directory.name)
    meta: dict[str, object] = {"id": project.id, "created": project.created}
    if title:
        meta["title"] = title
    meta[FORMAT_KEY] = FORMAT.current_version
    write_atomic(
        directory / PROJECT_META,
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    write_pointer(directory)
    return directory
