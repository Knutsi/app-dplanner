"""The library format's history.

One tuple, appended to and never edited. The engine is in
:mod:`dplanner.core.formats`; the rules it enforces are worth restating here because this is
the file you will be tempted to break:

- A new format version is a **new entry at the end**. Never change an existing one — a
  folder written by version 1 walks the whole chain, and each step's output is the next
  step's input.
- ``node`` runs per node as it loads, with the raw dict it came from, so it can reach keys
  the model no longer has fields for. ``whole`` runs once over each finished *project* —
  the aggregate a format version covers, since every ``project.dproj`` migrates on its own.
- Bumping the version is exactly this edit. ``FORMAT.current_version`` is derived.

**Version 2 dealt every step its number.** A step's ``number`` and the project's
``last_number`` (``model.py``: minted at ``add_child``, never reused) did not exist before;
the migration numbers a version-1 project's steps in the order its ``children`` list
records — the order the project has always shown them in — and sets the mark past the
last. A ``whole`` hook, because a number is dealt per project and a per-node hook cannot
see its siblings.

**Version 3 made the code repository a row of the locations table.** ``"repository"`` on
the project — one string, the code repository's remote — became the first ``code`` row of
``"locations"`` (``domain/locations.py``), so a project can name several repositories,
each with a role and a position. A ``node`` hook, because the old key is read off the raw
dict the model no longer has a field for; a project with no ``repository`` gets no row,
and still reads as the older shape.
"""

from pathlib import Path
from typing import Any

from dplanner.core.formats import FormatHistory, Migration
from dplanner.domain.locations import CODE, Location
from dplanner.domain.model import Node, Project, next_number


def _deal_numbers(project: Project) -> None:
    for step in project.steps:
        if not step.number:
            step.number = next_number(project)
            project.last_number = step.number


def _repository_to_location(node: Node, raw: dict[str, Any], _directory: Path) -> None:
    repository = raw.get("repository")
    if isinstance(node, Project) and isinstance(repository, str) and repository:
        node.locations = (Location("l1", CODE.id, repository),)


MIGRATIONS: tuple[Migration[Node, Project], ...] = (
    Migration(
        version=2,
        note="every step carries a per-project number; the project keeps the high-water mark",
        whole=_deal_numbers,
    ),
    Migration(
        version=3,
        note="the code repository is the first code row of the project's locations table",
        node=_repository_to_location,
    ),
)

FORMAT: FormatHistory[Node, Project] = FormatHistory(MIGRATIONS, oldest_readable=1)
